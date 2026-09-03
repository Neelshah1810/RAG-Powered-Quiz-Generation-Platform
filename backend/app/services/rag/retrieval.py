"""
Academix AI — Retrieval (PRD §8.2 Stage 3).

Hybrid retrieval over Supabase pgvector: dense similarity plus a keyword rank,
combined server-side by the `match_chunks` RPC, with course / source_type /
exam_type / topic applied as **hard** metadata filters.

PRD §15 names the failure this design guards against — "retrieval pulls an
irrelevant chunk, producing an off-syllabus question" — and prescribes "hybrid
retrieval with hard metadata filters … not pure semantic search".
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import get_settings
from app.database import get_supabase_admin
from app.models.rag import SourceChunk
from app.services.rag.embeddings import generate_query_embedding

logger = logging.getLogger(__name__)


async def _course_chunk_count(course_id: str, source_type: Optional[str] = None) -> int:
    """How many indexed chunks a course currently has (capped probe)."""
    query = (
        get_supabase_admin()
        .table("content_chunks")
        .select("id", count="exact")
        .eq("course_id", course_id)
    )
    if source_type:
        query = query.eq("source_type", source_type)
    try:
        result = query.limit(1).execute()
        return int(result.count or 0)
    except Exception as exc:
        logger.warning("Could not count chunks for course %s: %s", course_id, exc)
        return 0


def _merge_chunks(*groups: list[SourceChunk], limit: int) -> list[SourceChunk]:
    """Deduplicate by id, preserving order across groups."""
    seen: set[str] = set()
    merged: list[SourceChunk] = []
    for group in groups:
        for chunk in group:
            if chunk.id in seen:
                continue
            seen.add(chunk.id)
            merged.append(chunk)
            if len(merged) >= limit:
                return merged
    return merged


async def retrieve_chunks(
    query: str,
    course_id: str,
    source_type: Optional[str] = None,
    exam_type: Optional[str] = None,
    topic_tag: Optional[str] = None,
    top_k: Optional[int] = None,
    threshold: Optional[float] = None,
) -> list[SourceChunk]:
    """
    Fetch the chunks most relevant to `query` within one course.

    `exam_type` deliberately does **not** filter content chunks: an internal
    exam is drawn from the same lecture material as an external one. It is
    forwarded only when narrowing to the PYQ corpus, where a chunk's exam_type
    is meaningful.

    Small corpora (or the degraded hash embedding provider) load the full
    course corpus so generation is always grounded in real uploaded material
    rather than sparse / empty retrieval results.
    """
    settings = get_settings()
    supabase = get_supabase_admin()

    top_k = top_k or settings.RETRIEVAL_TOP_K
    threshold = settings.RETRIEVAL_THRESHOLD if threshold is None else threshold

    # Prefer the entire corpus when it fits in the context window budget —
    # this is the common case for a newly uploaded single notes file.
    corpus_size = await _course_chunk_count(course_id, source_type)
    use_full_corpus = corpus_size > 0 and corpus_size <= max(top_k * 2, 24)

    from app.services.rag.embeddings import get_provider

    provider = get_provider()
    degraded = provider.name.startswith("hash")

    query = (query or "").strip()
    if not query or use_full_corpus:
        sample_limit = max(top_k, corpus_size or top_k)
        return await sample_course_chunks(course_id, source_type, sample_limit)

    try:
        query_embedding = generate_query_embedding(query)
    except Exception as exc:
        logger.error("Could not embed retrieval query: %s", exc)
        return await sample_course_chunks(course_id, source_type, top_k)

    # Hash embeddings are lexical-only; drop the similarity floor so keyword
    # overlap still surfaces the uploaded notes.
    effective_threshold = -1.0 if degraded else threshold

    try:
        result = supabase.rpc(
            "match_chunks",
            {
                "query_embedding": query_embedding,
                "p_course_id": course_id,
                "p_source_type": source_type,
                "p_exam_type": exam_type,
                "p_topic_tag": topic_tag,
                "p_query_text": query,
                "match_threshold": effective_threshold,
                "match_count": top_k,
                "keyword_weight": settings.RETRIEVAL_KEYWORD_WEIGHT,
            },
        ).execute()
    except Exception as exc:
        logger.error("match_chunks RPC failed: %s", exc)
        raise RuntimeError(
            "Vector search is unavailable. The match_chunks function may be "
            "missing or out of date — run `python -m scripts.migrate`. "
            f"Underlying error: {exc}"
        ) from exc

    ranked = _to_source_chunks(result.data or [])
    if not ranked and not degraded:
        logger.info(
            "No chunks above threshold %.2f for course %s; retrying unfiltered",
            threshold,
            course_id,
        )
        ranked = await _retry_without_threshold(
            query_embedding, query, course_id, source_type, topic_tag, top_k
        )

    # Always backfill with a corpus sample so generation never runs on an
    # empty / near-empty context when material exists.
    sample = await sample_course_chunks(course_id, source_type, top_k)
    return _merge_chunks(ranked, sample, limit=max(top_k, 12))


async def _retry_without_threshold(
    query_embedding: list[float],
    query: str,
    course_id: str,
    source_type: Optional[str],
    topic_tag: Optional[str],
    top_k: int,
) -> list[SourceChunk]:
    try:
        result = get_supabase_admin().rpc(
            "match_chunks",
            {
                "query_embedding": query_embedding,
                "p_course_id": course_id,
                "p_source_type": source_type,
                "p_exam_type": None,
                "p_topic_tag": topic_tag,
                "p_query_text": query,
                "match_threshold": -1.0,  # accept anything, keep the ranking
                "match_count": top_k,
                "keyword_weight": get_settings().RETRIEVAL_KEYWORD_WEIGHT,
            },
        ).execute()
    except Exception as exc:
        logger.error("Unfiltered match_chunks retry failed: %s", exc)
        return []
    return _to_source_chunks(result.data or [])


async def sample_course_chunks(
    course_id: str,
    source_type: Optional[str] = None,
    limit: int = 12,
) -> list[SourceChunk]:
    """
    A plain slice of a course's corpus, ignoring relevance.

    Used when there is no query to rank against (a student asking for a quiz
    "on everything") or when embedding is unavailable.
    """
    supabase = get_supabase_admin()
    query = (
        supabase.table("content_chunks")
        .select("id, document_id, text, topic_tag, page_ref, source_type, exam_type, chunk_index")
        .eq("course_id", course_id)
    )
    if source_type:
        query = query.eq("source_type", source_type)

    try:
        result = query.order("chunk_index").limit(limit).execute()
    except Exception as exc:
        logger.error("Corpus sample failed for course %s: %s", course_id, exc)
        return []

    return _to_source_chunks(result.data or [])


def _to_source_chunks(rows: list[dict]) -> list[SourceChunk]:
    """Attach document names and convert RPC rows into SourceChunk models."""
    if not rows:
        return []

    document_ids = list({row["document_id"] for row in rows if row.get("document_id")})
    names: dict[str, str] = {}
    if document_ids:
        try:
            documents = (
                get_supabase_admin()
                .table("content_documents")
                .select("id, file_name")
                .in_("id", document_ids)
                .execute()
            )
            names = {d["id"]: d["file_name"] for d in (documents.data or [])}
        except Exception as exc:
            logger.warning("Could not resolve document names: %s", exc)

    chunks: list[SourceChunk] = []
    for row in rows:
        chunks.append(
            SourceChunk(
                id=row["id"],
                text=row["text"],
                document_id=row.get("document_id"),
                document_name=names.get(row.get("document_id", ""), "Unknown document"),
                page_ref=row.get("page_ref"),
                source_type=row.get("source_type", "notes"),
                topic_tag=row.get("topic_tag"),
                similarity=row.get("similarity"),
                hybrid_score=row.get("hybrid_score"),
            )
        )
    return chunks


async def retrieve_pyq_exemplars(
    course_id: str,
    exam_type: str,
    topic_tag: Optional[str] = None,
    count: int = 8,
) -> list[dict]:
    """
    Historical PYQ questions to use as *style* exemplars for Paper Style.

    PRD §8.2 Stage 3: these are "used as pattern reference only, never copied
    verbatim" — the generation prompt states that constraint explicitly.

    Sampled across sections rather than taken as the first N rows, so the
    exemplars show the shape of a whole paper instead of only its opening
    two-mark questions.
    """
    supabase = get_supabase_admin()

    query = (
        supabase.table("pyq_questions")
        .select("question_text, marks, section, question_type, bloom_level, topic_tag, year")
        .eq("course_id", course_id)
        .eq("exam_type", exam_type)
    )
    if topic_tag:
        query = query.eq("topic_tag", topic_tag)

    try:
        result = query.limit(200).execute()
    except Exception as exc:
        logger.warning("PYQ exemplar lookup failed: %s", exc)
        return []

    rows = result.data or []
    if len(rows) <= count:
        return rows

    # Round-robin across sections so every part of the paper is represented.
    by_section: dict[str, list[dict]] = {}
    for row in rows:
        by_section.setdefault(row.get("section") or "_", []).append(row)

    exemplars: list[dict] = []
    while len(exemplars) < count:
        added = False
        for bucket in by_section.values():
            if bucket:
                exemplars.append(bucket.pop(0))
                added = True
                if len(exemplars) == count:
                    break
        if not added:
            break

    return exemplars
