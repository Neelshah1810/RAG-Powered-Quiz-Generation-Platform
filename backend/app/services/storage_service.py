"""
Academix AI — Object storage.

All course material and student submissions live in private Supabase Storage
buckets; the browser never touches them directly. Reads are served through
short-lived signed URLs minted only after the caller has passed the
authorization checks in `authz.py` (PRD §13 Security, §14 role isolation).

The previous implementation had three problems this module fixes:
  * upload options were passed positionally in the wrong shape, so `upsert`
    never took effect and re-uploading a file 409'd;
  * a failed upload was swallowed and the material row was saved anyway with a
    fabricated `local/...` path, producing records whose files did not exist;
  * `create_signed_url` was read with the wrong response key, so downloads
    returned an empty URL.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from typing import Optional

from fastapi import HTTPException, status

from app.config import get_settings
from app.database import get_supabase_admin

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(RuntimeError):
    """Raised when object storage cannot complete an operation."""


def sanitise_filename(file_name: str) -> str:
    """
    Make a filename safe for use as a storage object key.

    Supabase keys reject a range of characters, and non-ASCII names come back
    mangled, so fold to ASCII and collapse anything else to a hyphen while
    keeping the extension intact.
    """
    name = unicodedata.normalize("NFKD", file_name or "file")
    name = name.encode("ascii", "ignore").decode("ascii")

    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""

    stem = _UNSAFE.sub("-", stem).strip("-._") or "file"
    extension = _UNSAFE.sub("", extension).lower()

    # Leave headroom for the path prefix within Supabase's key length limit.
    stem = stem[:120]
    return f"{stem}.{extension}" if extension else stem


def build_object_key(*parts: str, file_name: str, unique: bool = True) -> str:
    """
    Compose a storage key like `<course_id>/<uuid>-<safe-name>`.

    The uuid prefix means two teachers uploading `notes.pdf` to the same course
    do not overwrite one another, while the readable suffix keeps the bucket
    browsable in the Supabase dashboard.
    """
    safe = sanitise_filename(file_name)
    if unique:
        safe = f"{uuid.uuid4().hex[:12]}-{safe}"
    prefix = "/".join(p.strip("/") for p in parts if p)
    return f"{prefix}/{safe}" if prefix else safe


def upload_bytes(
    bucket: str,
    key: str,
    data: bytes,
    content_type: Optional[str] = None,
    *,
    upsert: bool = False,
) -> str:
    """
    Upload an object and return its `"<bucket>/<key>"` reference.

    Raises `StorageError` on failure — callers must not persist a database row
    pointing at a file that was never stored.
    """
    supabase = get_supabase_admin()
    options = {
        "content-type": content_type or "application/octet-stream",
        # supabase-py serialises these into HTTP headers, so they must be
        # strings, not bools.
        "upsert": "true" if upsert else "false",
        "cache-control": "3600",
    }

    try:
        supabase.storage.from_(bucket).upload(path=key, file=data, file_options=options)
    except Exception as exc:
        message = str(exc)
        if "already exists" in message.lower() or "duplicate" in message.lower():
            try:
                supabase.storage.from_(bucket).update(path=key, file=data, file_options=options)
                return f"{bucket}/{key}"
            except Exception as update_exc:
                raise StorageError(
                    f"Object '{key}' exists in '{bucket}' and could not be replaced: {update_exc}"
                ) from update_exc
        raise StorageError(f"Upload to '{bucket}/{key}' failed: {message}") from exc

    return f"{bucket}/{key}"


def split_reference(file_url: str, default_bucket: str) -> tuple[str, str]:
    """Split a stored `"<bucket>/<key>"` reference, tolerating a bare key."""
    settings = get_settings()
    known = {
        settings.BUCKET_MATERIALS,
        settings.BUCKET_PYQ,
        settings.BUCKET_SUBMISSIONS,
        settings.BUCKET_AVATARS,
        # The earliest build wrote into a bucket simply called "materials";
        # keep reading those rows rather than orphaning them.
        "materials",
    }
    if "/" in file_url:
        head, _, tail = file_url.partition("/")
        if head in known:
            return head, tail
    return default_bucket, file_url.lstrip("/")


def create_signed_url(
    file_url: str,
    default_bucket: str,
    *,
    download_name: Optional[str] = None,
    expires_in: Optional[int] = None,
) -> str:
    """
    Mint a short-lived signed URL for a private object.

    `download_name` sets the filename the browser saves as, so a student
    downloads "Unit 3 Notes.pdf" rather than "a1b2c3-unit-3-notes.pdf".
    """
    settings = get_settings()
    bucket, key = split_reference(file_url, default_bucket)
    ttl = expires_in or settings.SIGNED_URL_TTL_SECONDS

    options = {"download": download_name} if download_name else None

    try:
        response = get_supabase_admin().storage.from_(bucket).create_signed_url(
            path=key, expires_in=ttl, options=options
        )
    except Exception as exc:
        raise StorageError(f"Could not sign '{bucket}/{key}': {exc}") from exc

    # The key has moved across supabase-py versions; accept either spelling
    # rather than silently handing the frontend an empty string.
    if isinstance(response, dict):
        url = response.get("signedURL") or response.get("signedUrl") or response.get("signed_url")
        if url:
            # Older versions return a path relative to the storage endpoint.
            if url.startswith("/"):
                return f"{settings.SUPABASE_URL}/storage/v1{url}"
            return url

    raise StorageError(f"Storage returned no signed URL for '{bucket}/{key}': {response!r}")


def download_bytes(file_url: str, default_bucket: str) -> bytes:
    bucket, key = split_reference(file_url, default_bucket)
    try:
        return get_supabase_admin().storage.from_(bucket).download(key)
    except Exception as exc:
        raise StorageError(f"Could not download '{bucket}/{key}': {exc}") from exc


def delete_object(file_url: str, default_bucket: str) -> None:
    """Best-effort delete; a missing object is not an error worth surfacing."""
    bucket, key = split_reference(file_url, default_bucket)
    try:
        get_supabase_admin().storage.from_(bucket).remove([key])
    except Exception as exc:
        logger.warning("Could not delete '%s/%s': %s", bucket, key, exc)


def assert_upload_allowed(file_name: str, size_bytes: int) -> None:
    """
    Validate an upload before it is stored (PRD §13: "uploaded files
    type/virus-scanned before ingestion").

    Extension and size are enforced here. Virus scanning needs an external
    scanner and is deliberately not faked — see docs/OPERATIONS.md.
    """
    from app.utils.file_parser import SUPPORTED_EXTENSIONS, file_extension

    settings = get_settings()

    if size_bytes <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")

    if size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is {size_bytes / 1_048_576:.1f} MB; the limit is "
            f"{settings.MAX_UPLOAD_MB} MB.",
        )

    extension = file_extension(file_name)
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"'.{extension or 'unknown'}' files cannot be indexed. "
            f"Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}.",
        )


def assert_submission_upload_allowed(file_name: str, size_bytes: int) -> None:
    """
    Validate a student submission.

    Deliberately more permissive than `assert_upload_allowed`: submissions are
    stored and handed back to the teacher, never parsed for the RAG index, so
    a .zip of source code or an image of handwritten work is legitimate. Only
    executables are refused.
    """
    from app.utils.file_parser import file_extension

    settings = get_settings()

    if size_bytes <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    if size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is {size_bytes / 1_048_576:.1f} MB; the limit is "
            f"{settings.MAX_UPLOAD_MB} MB.",
        )

    blocked = {
        "exe", "dll", "bat", "cmd", "com", "msi", "scr", "ps1",
        "vbs", "js", "jar", "sh", "app", "apk",
    }
    extension = file_extension(file_name)
    if extension in blocked:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"'.{extension}' files cannot be submitted. Upload a document, "
            f"archive or image instead.",
        )
