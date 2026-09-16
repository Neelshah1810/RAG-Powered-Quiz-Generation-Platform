"""
Academix AI — Embedding provider.

PRD §7 asks for embeddings "abstracted via the same provider interface …
swappable for on-prem/privacy needs", kept independent of Groq (which serves
LLM inference but no embedding models). This module is that abstraction.

Three backends, selected by `EMBEDDING_PROVIDER`:

  local  sentence-transformers on the CPU. Offline, free, no API key. Requires
         the MSVC runtime on Windows because torch ships native libraries.
  jina   Jina AI's hosted API. `jina-embeddings-v3` is a Matryoshka model, so
         we request exactly EMBEDDING_DIMENSION dims and the schema's
         vector(384) column stays valid.
  hash   Deterministic character-n-gram hashing into the same dimensionality.
         No dependencies, no network. Retrieval quality is clearly worse — this
         is a degradation path, not a recommendation, and it says so loudly.

Every backend returns L2-normalised vectors of exactly EMBEDDING_DIMENSION
floats, so cosine distance in pgvector behaves consistently across them.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from abc import ABC, abstractmethod
from functools import lru_cache

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when embeddings cannot be produced at all."""


def _l2_normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


class EmbeddingProvider(ABC):
    """Turns text into fixed-width, L2-normalised vectors."""

    name: str = "abstract"

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed several texts at once. Must preserve input order."""

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def warm_up(self) -> None:
        """Do any expensive one-off setup now rather than on first request."""
        self.embed("warm up")

    def describe(self) -> str:
        return f"{self.name} ({self.dimension}d)"


# ─────────────────────────────────────────────────────────────────────────────
# local — sentence-transformers
# ─────────────────────────────────────────────────────────────────────────────

class LocalEmbeddingProvider(EmbeddingProvider):
    name = "local/sentence-transformers"

    def __init__(self, model_name: str, dimension: int, batch_size: int) -> None:
        super().__init__(dimension)
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        # Double-checked locking: several concurrent requests must not each
        # load their own copy of the model into memory.
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except Exception as exc:  # ImportError, or torch's DLL failure
                    raise EmbeddingError(
                        f"Could not import sentence-transformers: {exc}. "
                        "On Windows this is usually a missing MSVC runtime "
                        "(https://aka.ms/vs/17/release/vc_redist.x64.exe). "
                        "Alternatively set EMBEDDING_PROVIDER=jina."
                    ) from exc

                model = SentenceTransformer(self.model_name)
                actual = model.get_sentence_embedding_dimension()
                if actual != self.dimension:
                    raise EmbeddingError(
                        f"Model {self.model_name!r} emits {actual}-dim vectors but "
                        f"EMBEDDING_DIMENSION is {self.dimension} and the database "
                        f"column is vector({self.dimension}). Pick a matching model "
                        f"or migrate the column."
                    )
                self._model = model
                logger.info("Loaded local embedding model %s (%dd)", self.model_name, actual)
        return self._model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        return [list(map(float, v)) for v in vectors]

    def warm_up(self) -> None:
        self._load()


# ─────────────────────────────────────────────────────────────────────────────
# jina — hosted API
# ─────────────────────────────────────────────────────────────────────────────

class JinaEmbeddingProvider(EmbeddingProvider):
    name = "jina"

    # Jina rejects oversized batches; 64 keeps requests comfortably small.
    API_BATCH = 64

    def __init__(self, api_key: str, model: str, base_url: str, dimension: int) -> None:
        super().__init__(dimension)
        if not api_key:
            raise EmbeddingError(
                "EMBEDDING_PROVIDER=jina but JINA_API_KEY is empty. "
                "Get a free key at https://jina.ai/embeddings/."
            )
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def _request(self, texts: list[str], task: str) -> list[list[float]]:
        payload = {
            "model": self.model,
            "task": task,
            "dimensions": self.dimension,
            "late_chunking": False,
            "embedding_type": "float",
            "input": texts,
        }
        try:
            response = httpx.post(
                self.base_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Jina embedding request failed: {exc}") from exc

        if response.status_code != 200:
            raise EmbeddingError(
                f"Jina embedding API returned {response.status_code}: {response.text[:300]}"
            )

        rows = response.json().get("data", [])
        if len(rows) != len(texts):
            raise EmbeddingError(
                f"Jina returned {len(rows)} embeddings for {len(texts)} inputs"
            )
        # The API does not guarantee response order, but does return an index.
        rows.sort(key=lambda r: r.get("index", 0))
        return [_l2_normalise([float(x) for x in r["embedding"]]) for r in rows]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), self.API_BATCH):
            # `retrieval.passage` is the asymmetric-retrieval task for indexed
            # documents; queries use `retrieval.query` via embed_query().
            out.extend(self._request(texts[start:start + self.API_BATCH], "retrieval.passage"))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._request([text], "retrieval.query")[0]

    def warm_up(self) -> None:
        # A single tiny call confirms the key works before any user hits it.
        self._request(["warm up"], "retrieval.query")


# ─────────────────────────────────────────────────────────────────────────────
# hash — dependency-free degradation path
# ─────────────────────────────────────────────────────────────────────────────

class HashingEmbeddingProvider(EmbeddingProvider):
    """
    Hashes word unigrams and character 4-grams into a fixed-width vector with
    sublinear term weighting. Purely lexical: it can match paraphrases only
    where they share surface forms, so semantic recall is poor compared with a
    real embedding model. Present so the platform keeps working (rather than
    500-ing) when no embedding backend is installed or reachable.
    """

    name = "hash (DEGRADED — lexical only)"

    _WORD = re.compile(r"[a-z0-9]+")

    def __init__(self, dimension: int) -> None:
        super().__init__(dimension)
        logger.warning(
            "EMBEDDING_PROVIDER=hash is in use. Retrieval quality will be "
            "substantially worse than with a real embedding model. Install the "
            "MSVC runtime and switch to EMBEDDING_PROVIDER=local, or set "
            "EMBEDDING_PROVIDER=jina with a JINA_API_KEY."
        )

    def _features(self, text: str) -> dict[str, float]:
        lowered = text.lower()
        counts: dict[str, int] = {}
        for word in self._WORD.findall(lowered):
            counts[f"w:{word}"] = counts.get(f"w:{word}", 0) + 1
        squashed = re.sub(r"\s+", " ", lowered)
        for i in range(len(squashed) - 3):
            gram = squashed[i:i + 4]
            counts[f"c:{gram}"] = counts.get(f"c:{gram}", 0) + 1
        # 1 + log(tf) damps the effect of a term repeated many times.
        return {k: 1.0 + math.log(v) for k, v in counts.items()}

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % self.dimension
        # Signed hashing keeps unrelated collisions from always reinforcing.
        sign = 1.0 if (value >> 63) & 1 else -1.0
        return index, sign

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for feature, weight in self._features(text).items():
                index, sign = self._bucket(feature)
                vector[index] += sign * weight
            out.append(_l2_normalise(vector))
        return out

    def warm_up(self) -> None:
        self.embed("warm up")


# ─────────────────────────────────────────────────────────────────────────────
# Selection
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache
def get_provider() -> EmbeddingProvider:
    """
    The configured provider, built once per process.

    `local` falls back to `hash` if its native dependencies cannot load, so an
    incomplete machine setup degrades the RAG engine instead of taking the
    whole API down. `jina` does not fall back: a misconfigured API key is an
    operator error worth surfacing.
    """
    settings = get_settings()
    choice = settings.EMBEDDING_PROVIDER

    if choice == "jina":
        return JinaEmbeddingProvider(
            api_key=settings.JINA_API_KEY,
            model=settings.JINA_MODEL,
            base_url=settings.JINA_BASE_URL,
            dimension=settings.EMBEDDING_DIMENSION,
        )

    if choice == "hash":
        return HashingEmbeddingProvider(settings.EMBEDDING_DIMENSION)

    provider = LocalEmbeddingProvider(
        model_name=settings.EMBEDDING_MODEL,
        dimension=settings.EMBEDDING_DIMENSION,
        batch_size=settings.EMBED_BATCH_SIZE,
    )
    try:
        provider.warm_up()
        return provider
    except EmbeddingError as exc:
        logger.error("Local embedding provider unavailable: %s", exc)
        logger.error("Falling back to the degraded 'hash' provider.")
        return HashingEmbeddingProvider(settings.EMBEDDING_DIMENSION)


def generate_embedding(text: str) -> list[float]:
    """Embed one passage of text."""
    return get_provider().embed(text)


def generate_query_embedding(text: str) -> list[float]:
    """
    Embed a search query.

    Asymmetric models (Jina v3) score noticeably better when queries and
    passages are embedded with different task prefixes; symmetric ones ignore
    the distinction, so this collapses to `generate_embedding` for them.
    """
    provider = get_provider()
    embed_query = getattr(provider, "embed_query", None)
    if callable(embed_query):
        return embed_query(text)
    return provider.embed(text)


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Embed many passages at once — far cheaper than looping."""
    return get_provider().embed_batch(texts)


def provider_description() -> str:
    return get_provider().describe()


# Kept so `main.py`'s startup hook and any older imports keep working.
def get_embedding_model() -> EmbeddingProvider:
    return get_provider()
