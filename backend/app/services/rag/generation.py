"""
Academix AI — Question generation (PRD §8.2 Stage 4).

One engine, two modes:

  quiz_generation  Student practice. Casual difficulty control, answer key and
                   explanation shown immediately, freely regenerable.
  paper_style      Teacher exam draft. Must obey the course's Style Profile —
                   section structure, marks-per-question, cognitive-level
                   spread — and every item carries source citations. Always
                   lands as "Draft — Needs Review".

Retrieved chunks are the **only** permitted factual source. The prompt says so,
the schema forces each question to name the chunk ids it used, and
`verification.py` then independently checks the claim (Stage 5).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.config import get_settings
from app.models.rag import GenerationRequest, SourceChunk
from app.services.rag.llm import complete_json, unwrap_list

logger = logging.getLogger(__name__)

BLOOM_LEVELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"]

DIFFICULTY_GUIDANCE = {
    "easy": (
        "Aim at recall and comprehension. Questions should be answerable "
        "directly from a single passage of the source material."
    ),
    "medium": (
        "Mix comprehension with application. Some questions should require "
        "combining two facts or applying a stated rule to a small example."
    ),
    "hard": (
        "Favour analysis and evaluation. Questions should require reasoning "
        "across several passages, comparing approaches, or judging trade-offs "
        "— while still being fully answerable from the source material."
    ),
}


def build_question_schema(allowed_types: list[str], require_sections: bool) -> dict[str, Any]:
    """
    JSON schema the model is *constrained* to emit.

    `strict: true` on Groq means the response is guaranteed to match this, so
    downstream code can index fields without defensive checks. Enumerating the
    permitted question types here is also what stops the model from quietly
    returning a `long_answer` when the student asked for MCQs only.
    """
    question_properties: dict[str, Any] = {
        "question_text": {
            "type": "string",
            "description": "The question as it should appear on the paper.",
        },
        "question_type": {"type": "string", "enum": list(allowed_types)},
        "options": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": (
                "Exactly four options for mcq, each prefixed 'A) ', 'B) ', "
                "'C) ', 'D) '. Null for every other question type."
            ),
        },
        "correct_answer": {
            "type": "string",
            "description": (
                "For mcq: the single letter A, B, C or D. For true_false: "
                "'True' or 'False'. Otherwise the model answer."
            ),
        },
        "explanation": {
            "type": "string",
            "description": "Why the answer is correct, citing the source material.",
        },
        "marks": {"type": "integer", "minimum": 1, "maximum": 50},
        "bloom_level": {"type": "string", "enum": BLOOM_LEVELS},
        "source_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Ids of the SOURCE blocks this question is grounded in.",
        },
    }
    required = [
        "question_text",
        "question_type",
        "options",
        "correct_answer",
        "explanation",
        "marks",
        "bloom_level",
        "source_ids",
    ]

    if require_sections:
        question_properties["section"] = {
            "type": "string",
            "description": "Section label from the style profile, e.g. 'A'.",
        }
        required.append("section")

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["questions"],
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": required,
                    "properties": question_properties,
                },
            }
        },
    }


def _format_context(chunks: list[SourceChunk]) -> str:
    """Render retrieved chunks as citable SOURCE blocks."""
    blocks: list[str] = []
    for chunk in chunks:
        header = f"[SOURCE id={chunk.id}]"
        provenance = chunk.document_name or "Unknown document"
        if chunk.page_ref:
            provenance += f", {chunk.page_ref}"
        blocks.append(f"{header}\nFrom: {provenance}\n{chunk.text}\n[/SOURCE]")
    return "\n\n".join(blocks)


def _format_style_profile(profile: dict) -> str:
    """Turn a stored style profile into instructions a model can follow."""
    lines: list[str] = []

    if profile.get("total_marks"):
        lines.append(f"- Target total marks for the paper: {profile['total_marks']}")
    if profile.get("duration_minutes"):
        lines.append(f"- Exam duration: {profile['duration_minutes']} minutes")

    sections = profile.get("section_structure") or []
    if sections:
        lines.append("- Section structure observed in past papers:")
        for section in sections:
            label = section.get("section") or "?"
            count = section.get("question_count")
            marks = section.get("marks_per_question")
            kind = section.get("common_type")
            detail = f"    Section {label}:"
            if count:
                detail += f" about {count} question(s)"
            if marks:
                detail += f" worth {marks} mark(s) each"
            if kind:
                detail += f", typically {str(kind).replace('_', ' ')}"
            lines.append(detail)

    bloom = profile.get("bloom_distribution") or {}
    if bloom:
        spread = ", ".join(
            f"{level} {round(share * 100)}%"
            for level, share in sorted(bloom.items(), key=lambda kv: -kv[1])
        )
        lines.append(f"- Cognitive-level spread to reproduce: {spread}")

    patterns = profile.get("common_patterns") or {}
    marks_distribution = patterns.get("marks_distribution") or {}
    if marks_distribution:
        common = ", ".join(
            f"{marks} marks (x{count})"
            for marks, count in sorted(
                marks_distribution.items(), key=lambda kv: -kv[1]
            )[:4]
        )
        lines.append(f"- Marks values that recur most: {common}")

    command_words = patterns.get("command_words") or []
    if command_words:
        lines.append(
            "- Command words this institute favours: "
            + ", ".join(str(w) for w in command_words[:10])
        )

    confidence = profile.get("confidence_score")
    if confidence is not None and confidence < 0.5:
        # PRD §15: below the data-volume threshold, say so instead of
        # over-fitting to two papers.
        lines.append(
            f"- NOTE: this profile is derived from limited data "
            f"(confidence {confidence:.2f}). Treat the structure as a guide, "
            f"not a rigid template."
        )

    return "\n".join(lines) if lines else "- No reliable historical pattern available yet."


def _format_exemplars(exemplars: list[dict]) -> str:
    if not exemplars:
        return ""
    lines = [
        "HISTORICAL QUESTION STYLE (phrasing/structure reference ONLY — never "
        "reuse or lightly reword these; they are past papers):"
    ]
    for question in exemplars:
        bits = []
        if question.get("section"):
            bits.append(f"Sec {question['section']}")
        if question.get("marks"):
            bits.append(f"{question['marks']}m")
        if question.get("bloom_level"):
            bits.append(question["bloom_level"])
        label = f"  [{' | '.join(bits)}] " if bits else "  "
        body = (question.get("question_text") or "").strip().replace("\n", " ")
        lines.append(f"{label}{body[:300]}")
    return "\n".join(lines)


_QUIZ_SYSTEM = (
    "You are Academix AI's quiz generator for a single college. You write "
    "practice questions strictly from the source material you are given. "
    "You never rely on outside knowledge, never invent facts absent from the "
    "sources, and always cite the source ids each question came from. If the "
    "sources do not support enough questions, you return fewer rather than "
    "padding with unsupported ones."
)

_EXAM_PREP_QUIZ_SYSTEM = (
    "You are Academix AI's exam-style practice generator for a single college. "
    "You write practice questions strictly from the lecture SOURCE MATERIAL, "
    "while matching the institute's EXAM STYLE (section structure, marks, "
    "command verbs, Bloom mix) learned from previous-year papers. You never "
    "copy a past question verbatim or with trivial rewording. Prefer shapes "
    "and angles that historically appear in this exam type so the student "
    "practises what is likely to come — without leaking the actual past paper. "
    "Every question must cite source ids from the SOURCE blocks."
)

_PAPER_SYSTEM = (
    "You are Academix AI's exam-paper drafting assistant for a single college. "
    "You draft exam questions strictly from the source material provided, "
    "following the institute's own historical exam style. You never rely on "
    "outside knowledge, never copy a past question verbatim, and always cite "
    "the source ids each question came from. Your output is a DRAFT for a "
    "teacher to review — accuracy and syllabus alignment matter more than "
    "volume, so return fewer questions rather than unsupported ones."
)


def _build_prompt(
    request: GenerationRequest,
    chunks: list[SourceChunk],
    style_profile: Optional[dict],
    exemplars: list[dict],
) -> str:
    context = _format_context(chunks)
    topics = ", ".join(request.topic_tags) if request.topic_tags else "any topic covered below"
    types = ", ".join(request.question_types)
    difficulty_note = DIFFICULTY_GUIDANCE.get(request.difficulty, "")

    steer = f"\nTEACHER/STUDENT REQUEST: {request.prompt.strip()}\n" if request.prompt else ""

    if request.mode == "paper_style":
        profile_text = (
            _format_style_profile(style_profile)
            if style_profile
            else (
                "- No style profile exists for this course and exam type yet. "
                "Use a conventional structure: short-answer questions worth 2 "
                "marks, then longer ones worth 5-10 marks."
            )
        )
        exemplar_text = _format_exemplars(exemplars)

        return f"""Draft a high-quality set of MAXIMUM {request.question_count} questions for a {request.exam_type} examination. Do not exceed this limit.

TOPICS: {topics}
ALLOWED QUESTION TYPES: {types}
DIFFICULTY: {request.difficulty} — {difficulty_note}
{steer}
INSTITUTE EXAM STYLE (reproduce this):
{profile_text}

{exemplar_text}

SOURCE MATERIAL — your ONLY permitted factual source:
{context}

RULES
1. Every question must be fully answerable from the SOURCE blocks above.
2. Every question must list the source id(s) it draws on in `source_ids`.
   Use the exact id strings from the SOURCE headers.
3. Never reproduce a historical question verbatim or with trivial rewording. Ensure very high quality, robust questions suitable for a formal paper.
4. Assign each question to a section consistent with the style profile, and
   choose marks values consistent with that section. Provide a high-quality explanation/answer key.
5. Spread cognitive levels to match the profile's distribution.
6. For `mcq`, give exactly four options prefixed "A) ", "B) ", "C) ", "D) ",
   with exactly one correct; `correct_answer` is that option's letter alone.
7. No two questions may test the same fact.
8. Maximum question limit is strictly {request.question_count}. If the sources support fewer sound questions, return fewer. Never return more."""

    # Student quiz — optional style-aware exam prep
    style_suffix = ""
    if request.style_aware and request.exam_type:
        from app.services.rag.tutor import build_exam_prep_quiz_prompt_suffix

        style_suffix = build_exam_prep_quiz_prompt_suffix(style_profile, exemplars)
        exam_line = f"TARGET EXAM: {request.exam_type}\n"
    else:
        exam_line = ""

    return f"""Generate a high-quality set of MAXIMUM {request.question_count} practice quiz questions. Do not exceed this limit under any circumstances.

{exam_line}TOPICS: {topics}
QUESTION TYPES: {types}
DIFFICULTY: {request.difficulty} — {difficulty_note}
{steer}
SOURCE MATERIAL — your ONLY permitted factual source:
{context}
{style_suffix}

RULES
1. Every question must be fully answerable from the SOURCE blocks above.
2. Every question must list the source id(s) it draws on in `source_ids`.
   Use the exact id strings from the SOURCE headers.
3. Write a high-quality, highly detailed explanation for each answer that helps the student truly understand the concept, as if they are preparing for a major exam.
4. For `mcq`, give exactly four options prefixed "A) ", "B) ", "C) ", "D) ",
   with exactly one correct; `correct_answer` is that option's letter alone.
5. Distractors must be plausible, challenging, and drawn from the same material — never
   joke options or "none of the above".
6. No two questions may test the same fact. Ensure variety in concepts tested.
7. Marks: 1 for mcq/true_false/fill_blank, 2-5 for written answers.
8. Maximum question limit is strictly {request.question_count}. If the sources support fewer sound questions, return fewer. Never return more.
9. Never copy a past-paper question verbatim."""


# ─────────────────────────────────────────────────────────────────────────────
# Normalisation
# ─────────────────────────────────────────────────────────────────────────────

_OPTION_PREFIX = re.compile(r"^\s*\(?([A-Da-d])[\)\.\:]?\s+")
_WHITESPACE = re.compile(r"\s+")


def _normalise_mcq(question: dict) -> dict | None:
    """
    Put an MCQ into a consistent shape, or reject it.

    `correct_answer` is stored as the bare option letter and options are always
    prefixed "A) ".."D) ". Auto-grading then compares letter to letter, which
    is what the old frontend check (`option.startsWith(answer[0])`) was
    fumbling — that matched any option whose text merely began with the same
    character as the answer.
    """
    options = question.get("options") or []
    options = [str(o).strip() for o in options if str(o).strip()]
    if len(options) < 2:
        return None
    options = options[:4]

    letters = ["A", "B", "C", "D"][: len(options)]
    bodies: list[str] = []
    for option in options:
        match = _OPTION_PREFIX.match(option)
        bodies.append(option[match.end():].strip() if match else option)

    raw_answer = str(question.get("correct_answer") or "").strip()
    answer_letter: str | None = None

    # 1. A bare letter, or a letter-prefixed restatement of the option.
    letter_match = _OPTION_PREFIX.match(raw_answer + " ") or re.match(
        r"^\s*\(?([A-Da-d])\)?\s*$", raw_answer
    )
    if letter_match:
        candidate = letter_match.group(1).upper()
        if candidate in letters:
            answer_letter = candidate

    # 2. Otherwise match the answer text against the option bodies.
    if answer_letter is None and raw_answer:
        target = _WHITESPACE.sub(" ", raw_answer).strip().lower()
        for letter, body in zip(letters, bodies):
            if _WHITESPACE.sub(" ", body).strip().lower() == target:
                answer_letter = letter
                break
        if answer_letter is None:
            for letter, body in zip(letters, bodies):
                normalised = _WHITESPACE.sub(" ", body).strip().lower()
                if target and (target in normalised or normalised in target):
                    answer_letter = letter
                    break

    if answer_letter is None:
        logger.warning(
            "Dropping MCQ whose correct_answer %r matches none of its options",
            raw_answer[:80],
        )
        return None

    question["options"] = [f"{letter}) {body}" for letter, body in zip(letters, bodies)]
    question["correct_answer"] = answer_letter
    return question


def _fingerprint(text: str) -> str:
    """Loose identity for near-duplicate detection."""
    return _WHITESPACE.sub(" ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip()


def _is_near_duplicate(candidate: str, seen: list[str]) -> bool:
    """
    Token-overlap (Jaccard) duplicate check.

    PRD §8.2 Stage 5 requires "no near-duplicate questions appear in one set" —
    exact-string matching misses "What is a B-tree?" vs "Define a B-tree."
    """
    tokens = set(candidate.split())
    if len(tokens) < 3:
        return candidate in seen
    for existing in seen:
        other = set(existing.split())
        if not other:
            continue
        overlap = len(tokens & other) / len(tokens | other)
        if overlap >= 0.75:
            return True
    return False


def normalise_questions(
    raw_questions: list[dict],
    request: GenerationRequest,
    valid_chunk_ids: set[str],
) -> list[dict]:
    """
    Clean, validate and de-duplicate the model's output.

    Drops anything unusable: empty text, an MCQ whose answer matches no option,
    a type the caller did not ask for, or a near-duplicate of an earlier item.
    Citations are intersected with the ids actually retrieved, so a hallucinated
    source id cannot masquerade as provenance.
    """
    allowed_types = set(request.question_types)
    cleaned: list[dict] = []
    fingerprints: list[str] = []

    for question in raw_questions:
        text = str(question.get("question_text") or "").strip()
        if len(text) < 10:
            continue

        question_type = str(question.get("question_type") or "").strip().lower()
        if question_type not in allowed_types:
            # The model answered in a shape nobody asked for. Keep it only if
            # it is at least a type this platform can render.
            if question_type not in {"mcq", "short_answer", "long_answer", "true_false", "fill_blank"}:
                continue
            logger.debug("Keeping off-spec question type %r", question_type)

        fingerprint = _fingerprint(text)
        if _is_near_duplicate(fingerprint, fingerprints):
            logger.debug("Dropping near-duplicate question: %s", text[:60])
            continue

        item: dict[str, Any] = {
            "question_text": text,
            "question_type": question_type,
            "options": question.get("options"),
            "correct_answer": str(question.get("correct_answer") or "").strip(),
            "explanation": (str(question.get("explanation")).strip() if question.get("explanation") else None),
            "bloom_level": (str(question.get("bloom_level") or "").strip().lower() or None),
            "section": (str(question.get("section")).strip() if question.get("section") else None),
        }

        if item["bloom_level"] not in BLOOM_LEVELS:
            item["bloom_level"] = None

        try:
            marks = int(question.get("marks") or 1)
        except (TypeError, ValueError):
            marks = 1
        item["marks"] = max(1, min(marks, 50))

        if question_type == "mcq":
            normalised = _normalise_mcq(item)
            if normalised is None:
                continue
            item = normalised
        elif question_type == "true_false":
            item["options"] = None
            answer = item["correct_answer"].strip().lower()
            if answer in ("true", "t", "yes"):
                item["correct_answer"] = "True"
            elif answer in ("false", "f", "no"):
                item["correct_answer"] = "False"
            else:
                continue  # a true/false with neither answer is unusable
        else:
            item["options"] = None
            if not item["correct_answer"]:
                continue

        # Keep only citations that correspond to chunks we actually retrieved.
        cited = [str(s) for s in (question.get("source_ids") or [])]
        item["source_ids"] = [cid for cid in dict.fromkeys(cited) if cid in valid_chunk_ids]

        cleaned.append(item)
        fingerprints.append(fingerprint)

        if len(cleaned) >= request.question_count:
            break

    return cleaned


async def generate_questions(
    request: GenerationRequest,
    context_chunks: list[SourceChunk],
    style_profile: Optional[dict] = None,
    exemplars: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Generate and normalise a question set.

    Returns question dicts ready for verification and storage. An empty list
    means nothing usable could be grounded in the retrieved material.
    """
    settings = get_settings()

    if not context_chunks:
        return []

    prompt = _build_prompt(request, context_chunks, style_profile, exemplars or [])
    require_sections = request.mode == "paper_style"
    schema = build_question_schema(request.question_types, require_sections)

    # Roughly 350 output tokens per question, floor high enough that a small
    # set is never truncated mid-JSON, ceiling inside the model's limit.
    max_tokens = max(4096, min(request.question_count * 400 + 1500, 32000))

    if request.mode == "paper_style":
        system = _PAPER_SYSTEM
        temperature = 0.35
    elif request.style_aware:
        system = _EXAM_PREP_QUIZ_SYSTEM
        temperature = 0.45
    else:
        system = _QUIZ_SYSTEM
        temperature = 0.75

    parsed = await complete_json(
        system=system,
        user=prompt,
        model=settings.GROQ_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        json_schema=schema,
        schema_name="question_set",
    )

    raw_questions = unwrap_list(parsed, "questions")
    if not raw_questions:
        logger.warning(
            "Model returned no questions. Reply keys: %s",
            list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__,
        )
        return []

    valid_ids = {chunk.id for chunk in context_chunks}
    questions = normalise_questions(raw_questions, request, valid_ids)

    logger.info(
        "Generated %d/%d usable questions for %s (course %s)",
        len(questions),
        request.question_count,
        request.mode,
        request.course_id,
    )
    return questions


async def regenerate_single_question(
    request: GenerationRequest,
    context_chunks: list[SourceChunk],
    existing_questions: list[str],
    instruction: Optional[str] = None,
    style_profile: Optional[dict] = None,
) -> Optional[dict]:
    """
    Produce one replacement question that does not repeat the rest of the set.

    Backs the per-question "Regenerate" control in Paper Style review
    (PRD §8.2 Stage 6: "edit/regenerate/delete individual items").
    """
    settings = get_settings()
    if not context_chunks:
        return None

    avoid = "\n".join(f"  - {q[:200]}" for q in existing_questions[:30])
    single = request.model_copy(update={"question_count": 1})

    prompt = _build_prompt(single, context_chunks, style_profile, [])
    prompt += f"""

QUESTIONS ALREADY IN THIS SET — your new question must test something different:
{avoid or "  (none)"}
"""
    if instruction:
        prompt += f"\nADDITIONAL INSTRUCTION FOR THE REPLACEMENT: {instruction.strip()}\n"

    parsed = await complete_json(
        system=_PAPER_SYSTEM if request.mode == "paper_style" else _QUIZ_SYSTEM,
        user=prompt,
        model=settings.GROQ_MODEL,
        temperature=0.8,  # deliberately higher: the point is a different question
        max_tokens=2048,
        json_schema=build_question_schema(request.question_types, request.mode == "paper_style"),
        schema_name="question_set",
    )

    valid_ids = {chunk.id for chunk in context_chunks}
    candidates = normalise_questions(unwrap_list(parsed, "questions"), single, valid_ids)
    return candidates[0] if candidates else None


def validate_paper_format(
    questions: list[dict],
    style_profile: Optional[dict],
) -> list[str]:
    """
    Format validator for Paper Style (PRD §8.2 Stage 5, third bullet):
    "confirms marks sum correctly, section counts match the Style Profile, and
    no near-duplicate questions appear in one set."

    Returns human-readable warnings rather than rejecting the draft — the
    teacher is the decision-maker at Stage 6, so the job here is to tell them
    exactly where the draft deviates.
    """
    warnings: list[str] = []
    if not questions:
        return ["No questions were generated."]

    total_marks = sum(int(q.get("marks") or 0) for q in questions)

    if style_profile:
        expected_total = style_profile.get("total_marks")
        if expected_total:
            drift = total_marks - int(expected_total)
            # 10% tolerance: question counts rarely divide evenly into a target.
            if abs(drift) > max(2, int(expected_total) * 0.1):
                warnings.append(
                    f"Total marks is {total_marks}, but past {style_profile.get('exam_type', '')} "
                    f"papers total about {expected_total} ({drift:+d})."
                )

        expected_sections = {
            str(s.get("section")): s
            for s in (style_profile.get("section_structure") or [])
            if s.get("section")
        }
        if expected_sections:
            actual: dict[str, int] = {}
            for question in questions:
                label = str(question.get("section") or "unassigned")
                actual[label] = actual.get(label, 0) + 1

            missing = sorted(set(expected_sections) - set(actual))
            if missing:
                warnings.append(
                    f"No questions were assigned to section(s): {', '.join(missing)}."
                )

            unassigned = actual.get("unassigned", 0)
            if unassigned:
                warnings.append(f"{unassigned} question(s) have no section assigned.")

            for label, spec in expected_sections.items():
                expected_count = spec.get("question_count")
                got = actual.get(label, 0)
                if expected_count and got and abs(got - int(expected_count)) > 2:
                    warnings.append(
                        f"Section {label} has {got} question(s); past papers have "
                        f"about {expected_count}."
                    )

    # Duplicate sweep, independent of the generation-time filter — a teacher's
    # manual edits can reintroduce a collision after the fact.
    fingerprints: list[str] = []
    duplicates = 0
    for question in questions:
        fingerprint = _fingerprint(str(question.get("question_text") or ""))
        if _is_near_duplicate(fingerprint, fingerprints):
            duplicates += 1
        else:
            fingerprints.append(fingerprint)
    if duplicates:
        warnings.append(f"{duplicates} question(s) look like near-duplicates of another.")

    ungrounded = sum(1 for q in questions if not q.get("source_ids"))
    if ungrounded:
        warnings.append(
            f"{ungrounded} question(s) carry no source citation — review these closely."
        )

    return warnings


def summarise_bloom(questions: list[dict]) -> dict[str, float]:
    """Observed cognitive-level spread, for display next to the profile's target."""
    counts: dict[str, int] = {}
    for question in questions:
        level = question.get("bloom_level")
        if level:
            counts[level] = counts.get(level, 0) + 1
    total = sum(counts.values())
    if not total:
        return {}
    return {level: round(count / total, 2) for level, count in counts.items()}


def serialise_sources(question: dict, chunks: list[SourceChunk]) -> list[dict[str, Any]]:
    """
    Denormalise the cited chunks onto the question for the sources panel.

    Stored alongside the question so provenance survives even if the underlying
    document is later deleted or re-ingested — PRD §13 requires an approved
    set to keep "a full source-citation trail per question" permanently.
    """
    by_id = {chunk.id: chunk for chunk in chunks}
    cited = [by_id[cid] for cid in question.get("source_ids", []) if cid in by_id]

    # An uncited question still shows the top-ranked context, clearly labelled,
    # so a reviewer has something to check against.
    inferred = not cited
    if inferred:
        cited = chunks[:2]

    return [
        {
            "chunk_id": chunk.id,
            "text": chunk.text[:1200],
            "document_name": chunk.document_name,
            "page_ref": chunk.page_ref,
            "source_type": chunk.source_type,
            "similarity": round(chunk.similarity, 3) if chunk.similarity is not None else None,
            "inferred": inferred,
        }
        for chunk in cited
    ]


def dumps_compact(value: Any) -> str:
    """Stable JSON for logging generation configs."""
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)
