"""
Academix AI — Ingestion pipeline (PRD §8.2 Stage 1).

Runs as a FastAPI BackgroundTask whenever a teacher uploads through Classroom:

    download → extract text → chunk → embed → store
                                   └→ (PYQ only) extract question metadata
                                                  → recompute style profile

The PYQ branch is what makes Paper Style possible at all. PRD §8.2 Stage 1
requires that for previous-year papers we "extract structural metadata:
question text, marks, section, question type, and an LLM-assisted Bloom's
taxonomy level — this is what lets the engine learn 'exam style', not just
content." Without it `pyq_questions` stays empty, `compute_style_profile()`
always returns None, and Paper Style silently falls back to generic formatting.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.config import get_settings
from app.database import get_supabase_admin
from app.services.rag.embeddings import generate_embeddings
from app.services.rag.llm import LLMError, complete_json, unwrap_list
from app.utils.file_parser import count_pages, extract_text

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────────────────────────────

_PAGE_MARKER = re.compile(r"\[(Page|Slide) (\d+)\]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _split_long_paragraph(paragraph: str, limit: int) -> list[str]:
    """Break an over-long paragraph on sentence boundaries."""
    sentences = _SENTENCE_END.split(paragraph)
    pieces: list[str] = []
    buf: list[str] = []
    size = 0

    for sentence in sentences:
        words = len(sentence.split())
        if size + words > limit and buf:
            pieces.append(" ".join(buf))
            buf, size = [], 0
        # A single sentence longer than the limit (tables, dense formulae) is
        # emitted whole rather than cut mid-clause; the embedding model will
        # truncate it, but the stored text stays readable as a citation.
        buf.append(sentence)
        size += words

    if buf:
        pieces.append(" ".join(buf))
    return pieces


def chunk_text(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Split extracted text into ~`chunk_size`-word chunks with overlap.

    Splits on paragraph boundaries first so a chunk rarely starts mid-thought,
    and carries the trailing sentences of one chunk into the next so a fact
    spanning a boundary is still retrievable (PRD §8.2: "~300–500 tokens, with
    overlap"). Words are used as the unit rather than true BPE tokens — for
    English prose the ratio is stable enough, and it avoids a tokenizer
    dependency in the hot path.

    Each chunk records the page/slide it came from, which becomes the
    `page_ref` shown in the NotebookLM-style sources panel.
    """
    settings = get_settings()
    limit = chunk_size or settings.CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP

    # Track which page each paragraph belongs to as we walk the document.
    paragraphs: list[tuple[str, Optional[str]]] = []
    current_page: Optional[str] = None

    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        marker = _PAGE_MARKER.search(block)
        if marker:
            current_page = f"{marker.group(1)} {marker.group(2)}"
            block = _PAGE_MARKER.sub("", block).strip()
            if not block:
                continue
        paragraphs.append((block, current_page))

    chunks: list[dict[str, Any]] = []
    buf: list[str] = []
    buf_page: Optional[str] = None
    size = 0

    def flush() -> None:
        nonlocal buf, size, buf_page
        if not buf:
            return
        body = "\n\n".join(buf).strip()
        if body:
            chunks.append(
                {
                    "text": body,
                    "chunk_index": len(chunks),
                    "token_count": len(body.split()),
                    "page_ref": buf_page,
                }
            )
        # Carry the tail forward so context survives the boundary.
        if overlap > 0 and body:
            words = body.split()
            tail = " ".join(words[-overlap:]) if len(words) > overlap else body
            buf = [tail]
            size = len(tail.split())
        else:
            buf = []
            size = 0

    for paragraph, page in paragraphs:
        if buf_page is None:
            buf_page = page

        for piece in (
            _split_long_paragraph(paragraph, limit)
            if len(paragraph.split()) > limit
            else [paragraph]
        ):
            words = len(piece.split())
            if size + words > limit and buf:
                flush()
                buf_page = page
            buf.append(piece)
            size += words

    # Final flush must not re-seed an overlap chunk.
    if buf:
        body = "\n\n".join(buf).strip()
        # Guard against a trailing chunk that is nothing but the carried-over
        # overlap text, which would duplicate the previous chunk.
        is_pure_overlap = bool(chunks) and body and chunks[-1]["text"].endswith(body)
        if body and not is_pure_overlap:
            chunks.append(
                {
                    "text": body,
                    "chunk_index": len(chunks),
                    "token_count": len(body.split()),
                    "page_ref": buf_page,
                }
            )

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# PYQ structural extraction (PRD §8.2 Stage 1, PYQ branch)
# ─────────────────────────────────────────────────────────────────────────────

PYQ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {
        "total_marks": {
            "type": ["integer", "null"],
            "description": "Total marks for the whole paper, if printed on it.",
        },
        "duration_minutes": {
            "type": ["integer", "null"],
            "description": "Exam duration in minutes, if printed on the paper.",
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "question_text",
                    "marks",
                    "section",
                    "question_type",
                    "bloom_level",
                    "topic_tag",
                ],
                "properties": {
                    "question_text": {"type": "string"},
                    "marks": {"type": ["integer", "null"]},
                    "section": {
                        "type": ["string", "null"],
                        "description": "Section label as printed, e.g. 'A', 'B', 'Part I'.",
                    },
                    "question_type": {
                        "type": "string",
                        "enum": [
                            "mcq",
                            "short_answer",
                            "long_answer",
                            "numerical",
                            "essay",
                            "true_false",
                            "fill_blank",
                        ],
                    },
                    "bloom_level": {
                        "type": "string",
                        "enum": [
                            "remember",
                            "understand",
                            "apply",
                            "analyze",
                            "evaluate",
                            "create",
                        ],
                    },
                    "topic_tag": {
                        "type": ["string", "null"],
                        "description": "Short topic/unit label inferred from the question.",
                    },
                },
            },
        },
    },
}

_PYQ_SYSTEM = (
    "You are an exam-paper analyst. You read a previous-year university question "
    "paper and transcribe its questions together with their structural metadata. "
    "You never invent questions that are not in the paper, and you never answer "
    "them. If a field is not printed on the paper, return null for it rather "
    "than guessing — except question_type and bloom_level, which you always "
    "infer from the question's wording and command verb."
)

# A whole paper is usually well under this; the cap stops a mis-tagged 300-page
# textbook from being sent to the model in full.
_PYQ_MAX_CHARS = 60_000


def extract_pyq_questions(text: str, exam_type: Optional[str], year: Optional[int]) -> dict:
    """
    Pull individual questions and their metadata out of a PYQ paper.

    Returns `{"questions": [...], "total_marks": int|None,
    "duration_minutes": int|None}`. Raises LLMError if the model is unreachable
    so the caller can mark the document accordingly.
    """
    settings = get_settings()
    body = text[:_PYQ_MAX_CHARS]
    truncated = len(text) > _PYQ_MAX_CHARS

    prompt = f"""Transcribe every question from this question paper.

{"EXAM TYPE: " + exam_type if exam_type else ""}
{"YEAR: " + str(year) if year else ""}

For each question record:
  - question_text: the question as printed (drop the leading "Q1." numbering)
  - marks: the marks printed against it, else null
  - section: the section heading it sits under, else null
  - question_type: infer from its form
  - bloom_level: infer from the command verb ("define"/"list" -> remember,
    "explain"/"describe" -> understand, "compute"/"apply" -> apply,
    "compare"/"analyse" -> analyze, "justify"/"evaluate" -> evaluate,
    "design"/"propose" -> create)
  - topic_tag: a short subject-matter label, else null

Also record the paper's total_marks and duration_minutes if printed.

Treat sub-parts ("(a)", "(b)") as separate questions when they carry their own
marks; otherwise keep them together with their parent.
{"NOTE: the paper text was truncated, so transcribe only what appears below." if truncated else ""}

--- QUESTION PAPER ---
{body}
--- END ---"""

    parsed = complete_json(
        system=_PYQ_SYSTEM,
        user=prompt,
        model=settings.GROQ_MODEL,
        temperature=0.1,  # transcription, not creation
        max_tokens=16384,
        json_schema=PYQ_SCHEMA,
        schema_name="pyq_extraction",
    )

    if isinstance(parsed, list):
        parsed = {"questions": parsed}
    if not isinstance(parsed, dict):
        return {"questions": [], "total_marks": None, "duration_minutes": None}

    return {
        "questions": unwrap_list(parsed, "questions"),
        "total_marks": parsed.get("total_marks"),
        "duration_minutes": parsed.get("duration_minutes"),
    }


def _store_pyq_questions(
    document_id: str,
    course_id: str,
    exam_type: Optional[str],
    year: Optional[int],
    questions: list[dict],
) -> int:
    """Persist extracted PYQ questions. Returns the number stored."""
    supabase = get_supabase_admin()

    # Re-ingesting the same document should replace its questions, not stack
    # duplicates that would then skew the style profile.
    supabase.table("pyq_questions").delete().eq("document_id", document_id).execute()

    valid_bloom = {"remember", "understand", "apply", "analyze", "evaluate", "create"}
    records = []
    for question in questions:
        body = (question.get("question_text") or "").strip()
        if len(body) < 8:  # numbering fragments, stray headers
            continue

        marks = question.get("marks")
        try:
            marks = int(marks) if marks is not None else None
        except (TypeError, ValueError):
            marks = None

        bloom = (question.get("bloom_level") or "").strip().lower() or None
        if bloom not in valid_bloom:
            bloom = None  # the column has a CHECK constraint

        records.append(
            {
                "document_id": document_id,
                "course_id": course_id,
                "question_text": body[:4000],
                "marks": marks,
                "section": (question.get("section") or None),
                "question_type": (question.get("question_type") or None),
                "bloom_level": bloom,
                "topic_tag": (question.get("topic_tag") or None),
                "year": year,
                "exam_type": exam_type,
            }
        )

    if not records:
        return 0

    for start in range(0, len(records), 100):
        supabase.table("pyq_questions").insert(records[start : start + 100]).execute()
    return len(records)


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────


def resolve_storage_location(file_url: str, source_type: str) -> tuple[str, str]:
    """
    Split a stored `file_url` into (bucket, path).

    Values are written as "<bucket>/<path>", but tolerate a bare path by
    inferring the bucket from the document's source type.
    """
    settings = get_settings()
    known = {
        settings.BUCKET_MATERIALS,
        settings.BUCKET_PYQ,
        settings.BUCKET_SUBMISSIONS,
        settings.BUCKET_AVATARS,
    }

    if "/" in file_url:
        head, _, tail = file_url.partition("/")
        if head in known:
            return head, tail

    default = settings.BUCKET_PYQ if source_type == "pyq" else settings.BUCKET_MATERIALS
    return default, file_url.lstrip("/")


def _download(file_url: str, source_type: str) -> bytes:
    bucket, path = resolve_storage_location(file_url, source_type)
    try:
        return get_supabase_admin().storage.from_(bucket).download(path)
    except Exception as exc:
        raise RuntimeError(
            f"Could not download '{path}' from bucket '{bucket}': {exc}"
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────


def _fail(document_id: str, message: str) -> None:
    get_supabase_admin().table("content_documents").update(
        {"status": "failed", "error_message": message[:500]}
    ).eq("id", document_id).execute()
    logger.error("Ingestion failed for document %s: %s", document_id, message)


async def ingest_document(
    document_id: str,
    course_id: str,
    file_url: str,
    file_name: str,
    source_type: str,
    exam_type: Optional[str] = None,
    year: Optional[int] = None,
) -> None:
    """
    Ingest one uploaded document end to end.

    Never raises: this runs detached as a BackgroundTask, so a failure is
    recorded on the document row (status='failed' plus the reason, surfaced in
    the Classwork list) rather than thrown into a request nobody is awaiting.
    """
    supabase = get_supabase_admin()

    try:
        supabase.table("content_documents").update(
            {"status": "processing", "error_message": None}
        ).eq("id", document_id).execute()
    except Exception as exc:
        logger.error("Could not mark document %s as processing: %s", document_id, exc)
        return

    try:
        # 1. Fetch the raw file back out of object storage.
        file_bytes = _download(file_url, source_type)

        # 2. Extract text.
        text = extract_text(file_bytes, file_name)
        if not text or len(text.strip()) < 50:
            _fail(
                document_id,
                "No usable text could be extracted. If this is a scanned PDF it "
                "needs OCR before upload.",
            )
            return

        page_count = count_pages(file_bytes, file_name)

        # 3. Chunk.
        chunks = chunk_text(text)
        if not chunks:
            _fail(document_id, "Text extracted but produced no chunks.")
            return

        # 4. Embed in batches.
        embeddings = generate_embeddings([c["text"] for c in chunks])
        if len(embeddings) != len(chunks):
            _fail(
                document_id,
                f"Embedding count mismatch: {len(embeddings)} vectors for {len(chunks)} chunks.",
            )
            return

        # 5. Replace any chunks from a previous ingestion of this document, so a
        #    retry does not double-index the content.
        supabase.table("content_chunks").delete().eq("document_id", document_id).execute()

        records = [
            {
                "document_id": document_id,
                "course_id": course_id,
                "text": chunk["text"],
                "source_type": source_type,
                "exam_type": exam_type,
                "chunk_index": chunk["chunk_index"],
                "token_count": chunk["token_count"],
                "page_ref": chunk["page_ref"],
                "embedding": embedding,
            }
            for chunk, embedding in zip(chunks, embeddings)
        ]
        for start in range(0, len(records), 50):
            supabase.table("content_chunks").insert(records[start : start + 50]).execute()

        # 6. PYQ papers additionally get structural extraction + a style profile.
        pyq_note = ""
        if source_type == "pyq":
            pyq_note = await _ingest_pyq_structure(
                document_id=document_id,
                course_id=course_id,
                text=text,
                exam_type=exam_type,
                year=year,
            )

        supabase.table("content_documents").update(
            {
                "status": "indexed",
                "chunk_count": len(chunks),
                "page_count": page_count,
                "error_message": pyq_note or None,
            }
        ).eq("id", document_id).execute()

        logger.info(
            "Indexed document %s (%s): %d chunks%s",
            document_id,
            file_name,
            len(chunks),
            f" — {pyq_note}" if pyq_note else "",
        )

    except Exception as exc:  # noqa: BLE001 — background task must not escape
        logger.exception("Unhandled ingestion error for document %s", document_id)
        _fail(document_id, f"{type(exc).__name__}: {exc}")


async def _ingest_pyq_structure(
    document_id: str,
    course_id: str,
    text: str,
    exam_type: Optional[str],
    year: Optional[int],
) -> str:
    """
    Extract PYQ question metadata and refresh the style profile.

    Returns a short human-readable note, or "" on success with nothing to say.
    Chunking and embedding have already succeeded by this point, so a failure
    here degrades Paper Style's *style* fidelity but must not mark the whole
    document as failed — its content is still retrievable.
    """
    from app.services.rag import style_profile

    if not exam_type:
        return "Indexed for retrieval, but no exam type was set, so it cannot feed a style profile."

    try:
        extracted = extract_pyq_questions(text, exam_type, year)
    except LLMError as exc:
        logger.warning("PYQ metadata extraction failed for %s: %s", document_id, exc)
        return f"Content indexed; question-structure extraction failed ({exc})."

    stored = _store_pyq_questions(
        document_id=document_id,
        course_id=course_id,
        exam_type=exam_type,
        year=year,
        questions=extracted["questions"],
    )

    if stored == 0:
        return "Content indexed, but no exam questions were recognised in this file."

    try:
        await style_profile.compute_style_profile(
            course_id=course_id,
            exam_type=exam_type,
            printed_total_marks=extracted.get("total_marks"),
            printed_duration=extracted.get("duration_minutes"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Style profile recompute failed for %s/%s: %s", course_id, exam_type, exc)
        return f"Extracted {stored} question(s); style profile refresh failed ({exc})."

    logger.info("Extracted %d PYQ question(s) from document %s", stored, document_id)
    return ""
