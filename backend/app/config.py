"""
Academix AI — Application configuration.

Every setting is read from the environment (backend/.env in development); see
.env.example for the annotated list. Anything without a default here is
mandatory and the app will refuse to start without it, which is deliberate —
booting with a missing Supabase key would only fail later, per-request.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Supabase ────────────────────────────────────────────────────────────
    SUPABASE_URL: str
    SUPABASE_KEY: str            # anon / public key
    SUPABASE_SERVICE_KEY: str    # service_role key — server-side only
    SUPABASE_JWT_SECRET: str     # used to verify access tokens locally

    # Postgres URI. Only the migration runner needs it (scripts/migrate.py);
    # the app itself goes through the Supabase REST API.
    DATABASE_URL: str = ""

    # ── LLM (Groq) ──────────────────────────────────────────────────────────
    GROQ_API_KEY: str

    # Question generation. `openai/gpt-oss-120b` is the strongest model on Groq
    # that supports strict `json_schema` structured output, which is what lets
    # the generation pipeline skip defensive JSON parsing entirely.
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Verification and PYQ metadata extraction run once per question/paper and
    # are simple classification tasks, so they use the smaller, cheaper model.
    GROQ_VERIFY_MODEL: str = "openai/gpt-oss-20b"

    GROQ_TIMEOUT_SECONDS: float = 120.0
    GROQ_MAX_RETRIES: int = 2

    # ── Embeddings ──────────────────────────────────────────────────────────
    # "local" — sentence-transformers, runs offline, no API key. Needs the MSVC
    #           runtime on Windows (torch ships native libraries).
    # "jina"  — Jina AI's hosted embedding API. Needs JINA_API_KEY.
    # "hash"  — deterministic character-n-gram hashing. No dependencies and no
    #           network, but retrieval quality is markedly worse. It exists so
    #           the app degrades instead of dying when neither of the above is
    #           available; it logs a warning on every load.
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    # Must match `vector(N)` on content_chunks.embedding in the schema.
    # Changing it means a migration plus re-ingesting every document.
    EMBEDDING_DIMENSION: int = 384

    JINA_API_KEY: str = ""
    JINA_MODEL: str = "jina-embeddings-v3"
    JINA_BASE_URL: str = "https://api.jina.ai/v1/embeddings"

    # ── Chunking (PRD §8.2 Stage 1: ~300–500 tokens with overlap) ───────────
    CHUNK_SIZE: int = 400
    CHUNK_OVERLAP: int = 60
    EMBED_BATCH_SIZE: int = 32

    # ── Retrieval (PRD §8.2 Stage 3) ────────────────────────────────────────
    RETRIEVAL_TOP_K: int = 12
    RETRIEVAL_THRESHOLD: float = 0.25
    RETRIEVAL_KEYWORD_WEIGHT: float = 0.25

    # ── Generation limits ───────────────────────────────────────────────────
    MAX_QUESTIONS_PER_SET: int = 50
    # Above this count the faithfulness pass is skipped to stay inside the p95
    # latency budget in PRD §13; the set is flagged rather than silently passed.
    VERIFY_MAX_QUESTIONS: int = 25
    VERIFICATION_ENABLED: bool = True
    # Questions scoring below this on the faithfulness check are discarded
    # (PRD §8.2 Stage 5: "ungrounded items are discarded, never surfaced").
    FAITHFULNESS_MIN_SCORE: float = 0.5

    # ── Storage buckets ─────────────────────────────────────────────────────
    BUCKET_MATERIALS: str = "course-materials"
    BUCKET_PYQ: str = "pyq-papers"
    BUCKET_SUBMISSIONS: str = "submissions"
    BUCKET_AVATARS: str = "avatars"
    SIGNED_URL_TTL_SECONDS: int = 3600
    MAX_UPLOAD_MB: int = 50

    # ── Application ─────────────────────────────────────────────────────────
    APP_NAME: str = "Academix AI"
    APP_ENV: str = "development"
    DEBUG: bool = True
    FRONTEND_URL: str = "http://localhost:5173"
    # Comma-separated extra origins allowed by CORS, for staging/production.
    EXTRA_CORS_ORIGINS: str = ""
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    # Pre-load the embedding model during startup so the first generation
    # request isn't paying the load cost. Turn off for fast test boots.
    PRELOAD_EMBEDDING_MODEL: bool = True

    @field_validator("EMBEDDING_PROVIDER")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        allowed = {"local", "jina", "hash"}
        v = v.strip().lower()
        if v not in allowed:
            raise ValueError(f"EMBEDDING_PROVIDER must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("SUPABASE_URL")
    @classmethod
    def _clean_url(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        """Allowed browser origins, de-duplicated and order-preserving."""
        candidates = [
            self.FRONTEND_URL,
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
        candidates += [o.strip() for o in self.EXTRA_CORS_ORIGINS.split(",")]
        seen: set[str] = set()
        origins: list[str] = []
        for origin in candidates:
            origin = origin.rstrip("/")
            if origin and origin not in seen:
                seen.add(origin)
                origins.append(origin)
        return origins

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in ("production", "prod")


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — parsed once per process."""
    return Settings()  # type: ignore[call-arg]
