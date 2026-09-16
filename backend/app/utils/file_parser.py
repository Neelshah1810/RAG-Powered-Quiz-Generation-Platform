"""
Academix AI — Text extraction from uploaded files.

Feeds the ingestion pipeline (PRD §8.1: "PDF, DOCX, PPTX, TXT"). Every
extractor emits `[Page N]` / `[Slide N]` markers between units so the chunker
can attach a `page_ref` to each chunk, which is what the NotebookLM-style
sources panel cites back to the reader.

Uses `pypdf` rather than the deprecated `PyPDF2`, and every dependency here is
pure Python so extraction works on machines without a native toolchain.
"""

from __future__ import annotations

import io
import logging
import re

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (
    "pdf", "docx", "pptx", "txt", "md", "text", "csv", "json",
    "py", "js", "ts", "jsx", "tsx", "java", "cpp", "c", "cs", "go", "rs",
    "html", "css", "xml", "yaml", "yml", "sh", "log", "rtf", "sql"
)

# Encodings tried in order for plain-text uploads; utf-8-sig strips a BOM,
# cp1252 covers Word-exported text, latin-1 always succeeds as a last resort.
_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


class UnsupportedFileType(ValueError):
    """Raised for an extension we have no extractor for."""


def file_extension(file_name: str) -> str:
    return file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""


def is_supported(file_name: str) -> bool:
    ext = file_extension(file_name)
    blocked = {"exe", "dll", "bat", "cmd", "com", "msi", "scr", "ps1", "vbs", "jar", "apk", "app"}
    return ext not in blocked


def _tidy(text: str) -> str:
    """Normalise whitespace without destroying paragraph structure."""
    text = text.replace("\x00", "").replace("\u0000", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # PDF extraction commonly leaves hyphenated line breaks mid-word.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Collapse runs of spaces/tabs, but leave newlines alone.
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Three or more blank lines carry no more meaning than two.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Per-format extractors
# ─────────────────────────────────────────────────────────────────────────────


def extract_text_from_pdf(file_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))

    if getattr(reader, "is_encrypted", False):
        # Many "protected" academic PDFs use an empty owner password.
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError(
                "This PDF is password-protected and cannot be read."
            ) from exc

    parts: list[str] = []
    for number, page in enumerate(reader.pages, 1):
        try:
            body = page.extract_text() or ""
        except Exception as exc:  # a single malformed page must not lose the rest
            logger.warning("Skipped unreadable PDF page %d: %s", number, exc)
            continue
        if body.strip():
            parts.append(f"[Page {number}]\n{body.strip()}")

    if not parts:
        raise ValueError(
            "No text layer found in this PDF. Scanned documents need OCR "
            "before they can be indexed."
        )
    return _tidy("\n\n".join(parts))


def extract_text_from_docx(file_bytes: bytes) -> str:
    from docx import Document

    document = Document(io.BytesIO(file_bytes))
    parts: list[str] = [p.text.strip() for p in document.paragraphs if p.text.strip()]

    # Question papers and syllabi routinely put the real content in tables,
    # which document.paragraphs does not visit.
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                # De-duplicate merged cells, which repeat their text per span.
                seen: list[str] = []
                for cell in cells:
                    if not seen or seen[-1] != cell:
                        seen.append(cell)
                parts.append(" | ".join(seen))

    return _tidy("\n\n".join(parts))


def extract_text_from_pptx(file_bytes: bytes) -> str:
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(file_bytes))
    parts: list[str] = []

    for number, slide in enumerate(presentation.slides, 1):
        lines: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                body = shape.text_frame.text.strip()
                if body:
                    lines.append(body)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        lines.append(" | ".join(cells))

        # Speaker notes are often where the actual explanation lives.
        if slide.has_notes_slide:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
            if notes:
                lines.append(f"(Speaker notes) {notes}")

        if lines:
            parts.append(f"[Slide {number}]\n" + "\n".join(lines))

    return _tidy("\n\n".join(parts))


def extract_text_from_plain(file_bytes: bytes) -> str:
    for encoding in _TEXT_ENCODINGS:
        try:
            return _tidy(file_bytes.decode(encoding))
        except UnicodeDecodeError:
            continue
    return _tidy(file_bytes.decode("utf-8", errors="replace"))


# ─────────────────────────────────────────────────────────────────────────────
# Public entry points
# ─────────────────────────────────────────────────────────────────────────────


def extract_text(file_bytes: bytes, file_name: str) -> str:
    """
    Extract plain text from an uploaded file.
    Supports PDF, DOCX, PPTX, and falls back to plain-text reading for any text/code file.
    """
    extension = file_extension(file_name)

    try:
        if extension == "pdf":
            return extract_text_from_pdf(file_bytes)
        if extension == "docx":
            return extract_text_from_docx(file_bytes)
        if extension == "pptx":
            return extract_text_from_pptx(file_bytes)
        return extract_text_from_plain(file_bytes)
    except Exception as exc:
        # Fallback to plain text extraction
        try:
            return extract_text_from_plain(file_bytes)
        except Exception:
            raise ValueError(f"Could not extract text from '{file_name}': {exc}")


def count_pages(file_bytes: bytes, file_name: str) -> int | None:
    """Page/slide count for display, or None when the format has no concept of one."""
    extension = file_extension(file_name)
    try:
        if extension == "pdf":
            from pypdf import PdfReader

            return len(PdfReader(io.BytesIO(file_bytes)).pages)
        if extension == "pptx":
            from pptx import Presentation

            return len(Presentation(io.BytesIO(file_bytes)).slides)
    except Exception as exc:
        logger.debug("Page count unavailable for %s: %s", file_name, exc)
    return None


def get_page_ref(text: str, position: int) -> str | None:
    """
    The page/slide marker in effect at a character offset.

    Retained for callers outside the ingestion pipeline; `chunk_text()` tracks
    page context as it walks the document, which is both cheaper and accurate
    when the same text appears more than once.
    """
    if position < 0:
        position = 0
    window = text[: position + 200]
    best: tuple[int, str] | None = None
    for marker in ("[Page ", "[Slide "):
        index = window.rfind(marker)
        if index != -1 and (best is None or index > best[0]):
            end = window.find("]", index)
            if end != -1:
                best = (index, window[index + 1 : end])
    return best[1] if best else None
