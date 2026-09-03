"""
Academix AI — Student tutor orchestrator (intent-specialised RAG replies).

Takes a RoutedQuery + retrieved notes and produces a grounded reply. For
exam_prep / style-aware paths it loads the Style Profile and PYQ *patterns*
server-side only — raw previous-year question text is never returned to the
student (PRD §14).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.models.rag import SourceChunk
from app.services.rag import retrieval, style_profile
from app.services.rag.llm import LLMError, complete_text
from app.services.rag.query_router import RoutedQuery
from app.services.rag.generation import _format_style_profile

logger = logging.getLogger(__name__)

# Sources shown in the UI must never include PYQ document text.
_SAFE_SOURCE_TYPES = {"notes", "textbook"}


def _format_notes_context(chunks: list[SourceChunk], limit: int = 8) -> str:
    blocks: list[str] = []
    for chunk in chunks[:limit]:
        if chunk.source_type and chunk.source_type not in _SAFE_SOURCE_TYPES:
            # Still usable as private context for the model if we had pyq chunks,
            # but our retrieve_chunks for students should already be notes-first.
            continue
        provenance = chunk.document_name or "Course material"
        if chunk.page_ref:
            provenance += f" ({chunk.page_ref})"
        blocks.append(f"[{provenance}]\n{chunk.text}")
    if not blocks:
        # Fall back to whatever we retrieved (notes may be untyped).
        for chunk in chunks[:limit]:
            provenance = chunk.document_name or "Course material"
            blocks.append(f"[{provenance}]\n{chunk.text}")
    return "\n\n---\n\n".join(blocks)


def _safe_sources(chunks: list[SourceChunk], limit: int = 4) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if chunk.source_type and chunk.source_type not in _SAFE_SOURCE_TYPES | {None, ""}:
            if chunk.source_type == "pyq":
                continue
        out.append(
            {
                "document_name": chunk.document_name,
                "page_ref": chunk.page_ref,
                "text": (chunk.text or "")[:600],
                "source_type": chunk.source_type,
            }
        )
        if len(out) >= limit:
            break
    return out


def _sanitised_style_summary(profile: Optional[dict]) -> str:
    """Human-readable style hints safe to show a student (no PYQ verbatim)."""
    if not profile:
        return (
            "No historical exam style profile is available yet for this exam type. "
            "I'll lean on your lecture notes for now."
        )
    conf = float(profile.get("confidence_score") or 0)
    patterns = profile.get("common_patterns") or {}
    commands = patterns.get("command_words") or []
    sections = profile.get("section_structure") or []
    bloom = profile.get("bloom_distribution") or {}

    lines = [
        f"Exam type: {profile.get('exam_type')}",
        f"Style confidence: {conf:.0%} "
        f"(based on {profile.get('question_count') or 0} past questions across "
        f"{profile.get('pyq_count') or 0} paper(s))",
    ]
    if profile.get("total_marks"):
        lines.append(f"Typical total marks: {profile['total_marks']}")
    if profile.get("duration_minutes"):
        lines.append(f"Typical duration: {profile['duration_minutes']} minutes")
    if sections:
        bits = []
        for sec in sections[:6]:
            label = sec.get("section") or "?"
            n = sec.get("question_count")
            m = sec.get("marks_per_question")
            t = sec.get("common_type")
            bits.append(
                f"Sec {label}: ~{n} Qs"
                + (f" × {m} marks" if m else "")
                + (f" ({t})" if t else "")
            )
        lines.append("Section pattern: " + "; ".join(bits))
    if bloom:
        top = sorted(bloom.items(), key=lambda kv: -kv[1])[:4]
        lines.append(
            "Cognitive mix: "
            + ", ".join(f"{k} {int(v * 100)}%" for k, v in top)
        )
    if commands:
        lines.append("Common exam verbs: " + ", ".join(commands[:8]))
    if conf < 0.5:
        lines.append(
            "Note: style confidence is still low — treat this as a soft guide, "
            "not a guarantee of what will appear."
        )
    return "\n".join(f"- {line}" for line in lines)


def _history_block(history: list[dict]) -> str:
    if not history:
        return "(none)"
    lines = []
    for item in history[-8:]:
        role = "Student" if item.get("role") == "user" else "Tutor"
        lines.append(f"{role}: {str(item.get('content') or '')[:800]}")
    return "\n".join(lines)


_SYSTEMS = {
    "concept_explain": (
        "You are Academix AI, a concept tutor. Explain clearly using ONLY the "
        "SOURCE MATERIAL. Use short paragraphs or bullets. Define terms, give "
        "one concrete example from the notes when possible, and flag anything "
        "the notes do not cover. Never invent syllabus facts."
    ),
    "step_by_step": (
        "You are Academix AI, a worked-solution tutor. Give a numbered "
        "step-by-step reasoning path grounded ONLY in the SOURCE MATERIAL. "
        "Show intermediate reasoning; do not skip key steps. If the notes "
        "lack enough detail to solve fully, say what is missing."
    ),
    "study_guidance": (
        "You are Academix AI, a revision coach. Using the SOURCE MATERIAL and "
        "any EXAM STYLE SUMMARY, give a focused study plan: priority topics, "
        "what to practise, and how the institute tends to examine (if style "
        "data exists). Do NOT quote past exam questions verbatim. Do not "
        "invent topics absent from the notes."
    ),
    "exam_prep": (
        "You are Academix AI, an exam-prep coach for this college. Combine "
        "lecture notes with the EXAM STYLE SUMMARY (learned from past papers). "
        "Advise what is likely to be emphasised and how questions are typically "
        "phrased. NEVER reproduce a past paper question. NEVER reveal raw PYQ "
        "text. If the student wants a practice set, tell them you will open "
        "the quiz form styled for that exam."
    ),
    "general_chat": (
        "You are Academix AI, a helpful course tutor. Answer ONLY from the "
        "SOURCE MATERIAL. Be concise. If unsupported, say so. If they want a "
        "quiz or exam prep, invite them to ask for one."
    ),
}


async def load_exam_style_context(
    course_id: str,
    exam_type: str,
) -> tuple[Optional[dict], list[dict], str]:
    """
    Style profile + PYQ exemplars (server-only) + student-safe summary.

    Exemplars are for the generation/tutor prompt only — never serialised to
    the browser.
    """
    profile = await style_profile.get_style_profile(course_id, exam_type)
    exemplars = await retrieval.retrieve_pyq_exemplars(course_id, exam_type, count=8)
    summary = _sanitised_style_summary(profile)
    return profile, exemplars, summary


async def answer_routed(
    *,
    message: str,
    course_id: str,
    routed: RoutedQuery,
    history: list[dict],
    chunks: list[SourceChunk],
) -> tuple[str, list[dict[str, Any]], Optional[dict]]:
    """
    Produce (reply_text, safe_sources, style_meta).

    `style_meta` is a small dict the API may echo (exam_type, confidence, …)
    without any PYQ bodies.
    """
    notes = _format_notes_context(chunks)
    history_text = _history_block(history)
    style_meta: Optional[dict] = None
    style_block = ""
    exemplar_block = ""

    if routed.intent in ("exam_prep", "study_guidance") or routed.exam_type:
        exam_type = routed.exam_type or "internal"
        profile, exemplars, summary = await load_exam_style_context(course_id, exam_type)
        style_meta = {
            "exam_type": exam_type,
            "confidence_score": (profile or {}).get("confidence_score"),
            "pyq_count": (profile or {}).get("pyq_count") or 0,
            "question_count": (profile or {}).get("question_count") or 0,
            "has_profile": profile is not None,
        }
        style_block = f"EXAM STYLE SUMMARY (safe for student):\n{summary}\n"
        if exemplars and routed.intent == "exam_prep":
            # Pattern-only: strip to short stems for the model, still not returned.
            lines = [
                "HISTORICAL PATTERN STEMS (phrasing reference ONLY — never copy):"
            ]
            for ex in exemplars[:6]:
                stem = (ex.get("question_text") or "").strip().replace("\n", " ")[:160]
                bits = []
                if ex.get("marks"):
                    bits.append(f"{ex['marks']}m")
                if ex.get("section"):
                    bits.append(f"Sec {ex['section']}")
                if ex.get("bloom_level"):
                    bits.append(str(ex["bloom_level"]))
                label = f"[{' | '.join(bits)}] " if bits else ""
                lines.append(f"  {label}{stem}")
            exemplar_block = "\n".join(lines) + "\n"

    intent_key = routed.intent if routed.intent in _SYSTEMS else "general_chat"
    system = _SYSTEMS[intent_key]

    topics = ", ".join(routed.topic_hints) if routed.topic_hints else "general course content"
    user_prompt = (
        f"{style_block}"
        f"{exemplar_block}"
        f"SOURCE MATERIAL (lecture notes / textbook — ONLY factual source):\n{notes}\n\n"
        f"FOCUS TOPICS: {topics}\n"
        f"RECENT CHAT:\n{history_text}\n\n"
        f"Student: {message}\n\nTutor:"
    )

    try:
        reply = complete_text(
            system=system,
            user=user_prompt,
            temperature=0.25 if routed.intent == "step_by_step" else 0.35,
            max_tokens=1600 if routed.intent == "step_by_step" else 1200,
        )
    except LLMError:
        raise

    return reply, _safe_sources(chunks), style_meta


def style_aware_quiz_system() -> str:
    return (
        "You are Academix AI's exam-style practice generator for one college. "
        "You write practice questions strictly from the lecture SOURCE MATERIAL, "
        "while matching the institute's EXAM STYLE (marks, sections, command "
        "verbs, cognitive mix) learned from past papers. You never copy a past "
        "question verbatim or with trivial rewording. Every question must cite "
        "source ids. Prefer question shapes that historically appear in this "
        "exam type so the student practises what is likely to come — without "
        "leaking the actual past paper."
    )


def build_exam_prep_quiz_prompt_suffix(profile: Optional[dict], exemplars: list[dict]) -> str:
    """Extra instructions appended for style-aware student quizzes."""
    parts = [
        "\nEXAM-STYLE PRACTICE MODE",
        "Match the institute's historical exam pattern below.",
        "Prioritise topics/angles that recur in past papers, but ground every "
        "fact in the SOURCE MATERIAL only.",
        "Never reproduce a historical question.",
    ]
    if profile:
        parts.append("INSTITUTE EXAM STYLE:")
        parts.append(_format_style_profile(profile))
    if exemplars:
        parts.append(
            "PATTERN REFERENCE (structure/phrasing only — do not copy):"
        )
        for ex in exemplars[:8]:
            stem = (ex.get("question_text") or "").strip().replace("\n", " ")[:180]
            meta = []
            if ex.get("section"):
                meta.append(f"Sec {ex['section']}")
            if ex.get("marks"):
                meta.append(f"{ex['marks']}m")
            if ex.get("bloom_level"):
                meta.append(str(ex["bloom_level"]))
            if ex.get("question_type"):
                meta.append(str(ex["question_type"]))
            label = f"[{' | '.join(meta)}] " if meta else ""
            parts.append(f"  {label}{stem}")
    return "\n".join(parts)
