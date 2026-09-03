"""
Academix AI — Style Profile construction (PRD §8.2 Stage 2).

A Style Profile is the engine's learned representation of how *this* institute
examines *this* course, per exam type. Built from the `pyq_questions` rows that
ingestion extracts from uploaded previous-year papers, it captures:

  * typical total marks and duration
  * section structure ("Section A: 5 x 2 marks, short answer")
  * cognitive-level (Bloom's) distribution
  * recurring command words and marks values

PRD §15 requires a confidence indicator "below a data-volume threshold", with a
"generic formatting fallback until enough PYQs exist" — hence
`confidence_score`, which the generation prompt reads and downgrades its own
adherence accordingly.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Optional

from app.database import get_supabase_admin

logger = logging.getLogger(__name__)

# Below this, the sample is too small to describe a "style" at all.
MIN_QUESTIONS = 3

# Full confidence at this many extracted questions. Chosen so a course with
# 2-3 years of papers (PRD §17 assumes "at least 2-3 years of PYQs") lands near
# 1.0, while a single paper sits around 0.3 and is flagged as low confidence.
FULL_CONFIDENCE_QUESTIONS = 40

# Command verbs that carry a cognitive demand; "the" and "of" tell us nothing
# about exam style, so a plain word-frequency count would be noise.
_COMMAND_WORDS = {
    "define", "list", "state", "name", "identify", "recall", "outline",
    "explain", "describe", "discuss", "summarise", "summarize", "illustrate",
    "compute", "calculate", "solve", "apply", "implement", "demonstrate",
    "derive", "compare", "contrast", "analyse", "analyze", "differentiate",
    "classify", "examine", "justify", "evaluate", "assess", "critique",
    "argue", "design", "develop", "propose", "construct", "formulate",
    "write", "prove", "show", "draw", "sketch",
}

_WORD = re.compile(r"[a-z]+")


def _extract_command_words(questions: list[dict]) -> list[str]:
    """The command verbs this institute reaches for most often."""
    counter: Counter[str] = Counter()
    for question in questions:
        text = (question.get("question_text") or "").lower()
        # Weight the opening of the question: that is where the instruction is.
        for word in _WORD.findall(text)[:8]:
            if word in _COMMAND_WORDS:
                counter[word] += 1
    return [word for word, _ in counter.most_common(12)]


def _median(values: list[int]) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


async def compute_style_profile(
    course_id: str,
    exam_type: str,
    printed_total_marks: Optional[int] = None,
    printed_duration: Optional[int] = None,
) -> Optional[dict]:
    """
    Recompute and persist the Style Profile for one course + exam type.

    `printed_total_marks` / `printed_duration` come from the paper's own header
    when ingestion could read them — more trustworthy than summing extracted
    questions, since extraction may miss items or double-count sub-parts.

    Returns the stored profile, or None when there is too little data.
    """
    supabase = get_supabase_admin()

    result = (
        supabase.table("pyq_questions")
        .select("question_text, marks, section, question_type, bloom_level, topic_tag, year, document_id")
        .eq("course_id", course_id)
        .eq("exam_type", exam_type)
        .execute()
    )
    questions = result.data or []

    if len(questions) < MIN_QUESTIONS:
        logger.info(
            "Not enough PYQ data for %s/%s: %d question(s), need %d",
            course_id,
            exam_type,
            len(questions),
            MIN_QUESTIONS,
        )
        return None

    # ── Aggregate ────────────────────────────────────────────────────────────
    marks_per_paper: dict[str, int] = {}
    section_counter: Counter[str] = Counter()
    bloom_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()
    marks_counter: Counter[int] = Counter()
    documents: set[str] = set()

    for question in questions:
        document_id = question.get("document_id") or "unknown"
        documents.add(document_id)

        marks = question.get("marks")
        if isinstance(marks, int) and marks > 0:
            marks_per_paper[document_id] = marks_per_paper.get(document_id, 0) + marks
            marks_counter[marks] += 1

        if question.get("section"):
            section_counter[str(question["section"])] += 1
        if question.get("bloom_level"):
            bloom_counter[str(question["bloom_level"])] += 1
        if question.get("question_type"):
            type_counter[str(question["question_type"])] += 1

    # A paper's total is the median across papers, not the mean: one paper whose
    # marks failed to extract would drag a mean badly off.
    derived_total = _median([m for m in marks_per_paper.values() if m > 0])
    total_marks = printed_total_marks or derived_total

    total_bloom = sum(bloom_counter.values())
    bloom_distribution = (
        {level: round(count / total_bloom, 2) for level, count in bloom_counter.items()}
        if total_bloom
        else {}
    )

    # ── Section structure ────────────────────────────────────────────────────
    paper_count = max(1, len(marks_per_paper) or len(documents))
    section_structure: list[dict[str, Any]] = []

    for section, count in sorted(section_counter.items()):
        in_section = [q for q in questions if str(q.get("section") or "") == section]
        section_marks = [q["marks"] for q in in_section if isinstance(q.get("marks"), int)]
        section_types = [q["question_type"] for q in in_section if q.get("question_type")]

        section_structure.append(
            {
                "section": section,
                # Per *paper*, not across the whole corpus — otherwise a course
                # with three years of papers looks like it has 3x the questions.
                "question_count": max(1, round(count / paper_count)),
                "marks_per_question": (
                    Counter(section_marks).most_common(1)[0][0] if section_marks else None
                ),
                "common_type": (
                    Counter(section_types).most_common(1)[0][0] if section_types else None
                ),
                "total_observed": count,
            }
        )

    # ── Confidence (PRD §15) ─────────────────────────────────────────────────
    volume = min(1.0, len(questions) / FULL_CONFIDENCE_QUESTIONS)
    # Several papers agreeing is stronger evidence than one long paper.
    breadth = min(1.0, len(documents) / 3)
    # Structure we could actually read matters too: questions with no marks or
    # section tell us little about format.
    tagged = sum(
        1 for q in questions if q.get("marks") or q.get("section")
    ) / len(questions)
    confidence = round(0.5 * volume + 0.3 * breadth + 0.2 * tagged, 3)

    profile: dict[str, Any] = {
        "course_id": course_id,
        "exam_type": exam_type,
        "total_marks": total_marks,
        "duration_minutes": printed_duration,
        "section_structure": section_structure,
        "bloom_distribution": bloom_distribution,
        "common_patterns": {
            "question_types": dict(type_counter),
            "marks_distribution": {str(k): v for k, v in marks_counter.items()},
            "command_words": _extract_command_words(questions),
            "papers_analysed": len(documents),
        },
        "question_count": len(questions),
        "confidence_score": confidence,
        "pyq_count": len(documents),
        "last_computed_at": "now()",
    }

    # Preserve a duration read from an earlier paper if this one didn't print one.
    if printed_duration is None:
        existing = await get_style_profile(course_id, exam_type)
        if existing and existing.get("duration_minutes"):
            profile["duration_minutes"] = existing["duration_minutes"]

    supabase.table("style_profiles").upsert(
        profile, on_conflict="course_id,exam_type"
    ).execute()

    logger.info(
        "Style profile for %s/%s: %d questions across %d paper(s), confidence %.2f",
        course_id,
        exam_type,
        len(questions),
        len(documents),
        confidence,
    )
    return profile


async def get_style_profile(course_id: str, exam_type: str) -> Optional[dict]:
    """
    The stored Style Profile, or None.

    Uses a plain limited select rather than `.single()`: PostgREST's `single()`
    raises on zero rows, which turned "this course has no profile yet" — an
    entirely normal state — into a 500.
    """
    result = (
        get_supabase_admin()
        .table("style_profiles")
        .select("*")
        .eq("course_id", course_id)
        .eq("exam_type", exam_type)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


async def list_style_profiles(course_id: str) -> list[dict]:
    """Every profile for a course (internal and external)."""
    result = (
        get_supabase_admin()
        .table("style_profiles")
        .select("*")
        .eq("course_id", course_id)
        .execute()
    )
    return result.data or []
