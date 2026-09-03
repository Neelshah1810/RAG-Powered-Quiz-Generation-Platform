"""
Academix AI — LLM provider wrapper (Groq).

PRD §7 asks for Groq "abstracted via an internal LLMProvider interface", so
that swapping or benchmarking another provider is a change in one file rather
than three. Generation, verification and PYQ metadata extraction all go
through here.

The important capability this centralises is **strict structured output**.
`openai/gpt-oss-120b` on Groq supports `response_format={"type": "json_schema",
"json_schema": {..., "strict": True}}`, which means the model is constrained to
emit JSON matching our schema. That removes an entire class of failure the
earlier implementation tried to paper over with regex scraping of the reply.
`json_object` mode (schema-free) and plain text remain available for models or
tasks that do not need the guarantee.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when the model cannot produce a usable response."""


# Errors worth another attempt: transient capacity, rate limits, gateway blips.
_RETRYABLE_MARKERS = (
    "rate limit",
    "rate_limit",
    "429",
    "500",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "overloaded",
    "temporarily unavailable",
    "connection",
)


def _is_retryable(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _RETRYABLE_MARKERS)


_client = None


def get_client():
    """The shared Groq client (constructed once)."""
    global _client
    if _client is None:
        from groq import Groq

        settings = get_settings()
        if not settings.GROQ_API_KEY:
            raise LLMError("GROQ_API_KEY is not set — the RAG engine cannot generate.")
        _client = Groq(
            api_key=settings.GROQ_API_KEY,
            timeout=settings.GROQ_TIMEOUT_SECONDS,
            max_retries=0,  # retries are handled below so we can log them
        )
    return _client


def complete_text(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> str:
    """
    Plain-text chat completion (no JSON mode).

    Used by the student Quiz Generation chat tutor, where the reply is
    conversational prose grounded in retrieved course material.
    """
    settings = get_settings()
    model = model or settings.GROQ_VERIFY_MODEL or settings.GROQ_MODEL
    client = get_client()

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    attempts = max(1, settings.GROQ_MAX_RETRIES + 1)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise LLMError("Model returned an empty response")
            return content
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < attempts and _is_retryable(exc):
                backoff = 1.5 * attempt
                logger.warning(
                    "Groq text call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt,
                    attempts,
                    str(exc)[:200],
                    backoff,
                )
                time.sleep(backoff)
                continue
            break

    raise LLMError(f"Groq text request to {model} failed: {last_error}") from last_error


def complete(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.6,
    max_tokens: int = 8192,
    json_schema: dict[str, Any] | None = None,
    schema_name: str = "response",
) -> str:
    """
    Run one chat completion and return the raw message content.

    Pass `json_schema` to constrain the model to that exact JSON shape. If the
    model rejects strict schema mode, this degrades to schema-free JSON mode
    once rather than failing the request outright.
    """
    settings = get_settings()
    model = model or settings.GROQ_MODEL
    client = get_client()

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    if json_schema is not None:
        response_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": json_schema,
            },
        }
    else:
        response_format = {"type": "json_object"}

    attempts = max(1, settings.GROQ_MAX_RETRIES + 1)
    last_error: Exception | None = None
    schema_downgraded = False

    for attempt in range(1, attempts + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise LLMError("Model returned an empty response")
            return content

        except Exception as exc:  # noqa: BLE001 — provider raises many types
            last_error = exc
            message = str(exc)

            # Some models accept json_object but not strict json_schema. Try
            # once without the schema before giving up on the call.
            if (
                not schema_downgraded
                and json_schema is not None
                and ("json_schema" in message or "response_format" in message)
            ):
                logger.warning(
                    "Model %s rejected strict json_schema (%s); retrying in "
                    "schema-free JSON mode.",
                    model,
                    message[:160],
                )
                response_format = {"type": "json_object"}
                schema_downgraded = True
                continue

            if attempt < attempts and _is_retryable(exc):
                backoff = 1.5 * attempt
                logger.warning(
                    "Groq call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt,
                    attempts,
                    message[:200],
                    backoff,
                )
                time.sleep(backoff)
                continue

            break

    raise LLMError(f"Groq request to {model} failed: {last_error}") from last_error


def complete_json(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.6,
    max_tokens: int = 8192,
    json_schema: dict[str, Any] | None = None,
    schema_name: str = "response",
) -> Any:
    """
    Like `complete`, but parses the reply as JSON.

    With strict schema mode the reply is already valid JSON. The salvage step
    below only matters on the schema-free fallback path, where a model may wrap
    its JSON in prose or a ``` fence.
    """
    raw = complete(
        system=system,
        user=user,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        json_schema=json_schema,
        schema_name=schema_name,
    )

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        salvaged = _salvage_json(raw)
        if salvaged is not None:
            logger.warning("Recovered malformed JSON from %s", model or "model")
            return salvaged
        raise LLMError(
            f"Model reply was not valid JSON. First 400 chars: {raw[:400]}"
        ) from None


def _salvage_json(raw: str) -> Any | None:
    """
    Pull the first complete JSON object or array out of a noisy reply.

    Scans for a balanced bracket span rather than regex-matching, so nested
    structures and braces inside string literals do not truncate the match.
    """
    text = raw.strip()

    if text.startswith("```"):
        fence_end = text.find("\n")
        if fence_end != -1:
            text = text[fence_end + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : index + 1])
                    except json.JSONDecodeError:
                        break
    return None


def unwrap_list(parsed: Any, *keys: str) -> list[dict]:
    """
    Coerce a model reply into a list of dicts.

    Strict schema mode always returns an object wrapping the array (JSON schema
    root must be an object for `strict`), but the fallback path can return a
    bare array or a differently-named wrapper, so check the likely keys.
    """
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]

    if isinstance(parsed, dict):
        for key in (*keys, "questions", "items", "data", "results"):
            value = parsed.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        # A single object that looks like one record.
        if any(k in parsed for k in ("question_text", "text", "question")):
            return [parsed]

    return []
