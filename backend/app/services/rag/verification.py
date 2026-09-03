"""
Academix AI — Grounding & quality verification (PRD §8.2 Stage 5).

Two independent checks per question, run as a second LLM pass:

  Faithfulness  Is the question actually answerable from the chunks it cited,
                rather than from the model's own prior knowledge?
  Answer drift  Does the marked correct answer match what the source material
                actually says?

PRD §8.2: "ungrounded items are discarded/regenerated, never surfaced." So this
module *filters*, it does not merely annotate — the earlier implementation
computed a score and then returned every question regardless.

Verification is batched: one request covering the whole set rather than one per
question. A 20-question paper went from 20 sequential round-trips to 1, which
is the difference between blowing and meeting the p95 < 45s budget in PRD §13.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import get_settings
from app.models.rag import SourceChunk
from app.services.rag.llm import LLMError, complete_json

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a strict academic fact-checker. You are given exam questions "
    "together with the exact source passages they claim to be based on. For "
    "each question you decide, using ONLY those passages, whether the question "
    "is answerable from them and whether the marked answer is what the "
    "passages actually say. You do not use outside knowledge, and you do not "
    "reward a question for being generally true — only for being supported by "
    "the passages shown."
)

VERIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "index",
                    "answerable_from_sources",
                    "answer_matches_sources",
                    "faithfulness_score",
                    "reason",
                ],
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The question number given in the prompt.",
                    },
                    "answerable_from_sources": {"type": "boolean"},
                    "answer_matches_sources": {"type": "boolean"},
                    "faithfulness_score": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "1.0 = fully supported, 0.0 = unsupported.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "One sentence. Name the specific problem if any.",
                    },
                },
            },
        }
    },
}

# Per-question source budget, so a large set stays inside the model's context.
_MAX_SOURCE_CHARS = 2200
_BATCH_SIZE = 8


def _sources_for(question: dict, chunk_lookup: dict[str, SourceChunk], fallback: list[SourceChunk]) -> list[str]:
    """The passages a question claims to rest on."""
    cited = [chunk_lookup[cid].text for cid in question.get("source_ids", []) if cid in chunk_lookup]
    if not cited:
        # No citation: check it against the top-ranked context instead. If it
        # still cannot be grounded there, it genuinely should not be surfaced.
        cited = [chunk.text for chunk in fallback[:3]]
    return cited


def _render_batch(
    questions: list[dict],
    chunk_lookup: dict[str, SourceChunk],
    fallback: list[SourceChunk],
) -> str:
    blocks: list[str] = []
    for index, question in enumerate(questions, 1):
        sources = _sources_for(question, chunk_lookup, fallback)
        combined = "\n---\n".join(sources)[:_MAX_SOURCE_CHARS]

        answer = question.get("correct_answer", "")
        # An MCQ answer is stored as a bare letter; show the option text too or
        # the checker cannot judge whether "B" is right.
        options = question.get("options") or []
        if question.get("question_type") == "mcq" and options:
            answer = f"{answer} — {next((o for o in options if o.startswith(str(answer))), answer)}"

        blocks.append(
            f"""### QUESTION {index}
TYPE: {question.get('question_type')}
QUESTION: {question.get('question_text')}
MARKED ANSWER: {answer}

SOURCE PASSAGES FOR QUESTION {index}:
{combined}
"""
        )
    return "\n".join(blocks)


async def verify_question_set(
    questions: list[dict],
    source_chunks: list[SourceChunk],
) -> tuple[list[dict], list[dict]]:
    """
    Verify a whole set.

    Returns `(kept, rejected)`. Each kept question gains `faithfulness_score`
    and `verification_note`; each rejected one gains a `rejection_reason` so the
    caller can report *why* a set came back short instead of silently shrinking.

    If verification itself is unavailable (Groq down, or disabled by config),
    every question is kept and marked as unverified — refusing to surface any
    questions would be a worse failure than surfacing unchecked ones, and the
    UI shows the unverified state.
    """
    settings = get_settings()

    if not questions:
        return [], []

    if not settings.VERIFICATION_ENABLED:
        return _mark_unverified(questions, "Verification disabled by configuration"), []

    if len(questions) > settings.VERIFY_MAX_QUESTIONS:
        logger.info(
            "Skipping verification for %d questions (limit %d) to stay inside the latency budget",
            len(questions),
            settings.VERIFY_MAX_QUESTIONS,
        )
        return _mark_unverified(
            questions,
            f"Set exceeds the {settings.VERIFY_MAX_QUESTIONS}-question automatic "
            f"verification limit — review manually",
        ), []

    chunk_lookup = {chunk.id: chunk for chunk in source_chunks}
    verdicts: dict[int, dict] = {}

    for start in range(0, len(questions), _BATCH_SIZE):
        batch = questions[start : start + _BATCH_SIZE]
        try:
            parsed = complete_json(
                system=_SYSTEM,
                user=(
                    "Judge each question below against its own source passages.\n\n"
                    "Return one verdict per question, using the question numbers shown.\n"
                    "  answerable_from_sources: can the question be answered using only\n"
                    "    those passages?\n"
                    "  answer_matches_sources: is the marked answer what the passages say?\n"
                    "  faithfulness_score: 0.0-1.0 confidence that the question and its\n"
                    "    answer are fully supported.\n"
                    "  reason: one sentence; if there is a problem, say precisely what.\n\n"
                    + _render_batch(batch, chunk_lookup, source_chunks)
                ),
                model=settings.GROQ_VERIFY_MODEL,
                temperature=0.0,  # a judgement, not a generation
                max_tokens=4096,
                json_schema=VERIFICATION_SCHEMA,
                schema_name="verification",
            )
        except LLMError as exc:
            logger.warning("Verification batch starting at %d failed: %s", start, exc)
            continue

        rows = parsed.get("verdicts", []) if isinstance(parsed, dict) else []
        for row in rows:
            try:
                local_index = int(row.get("index", 0))
            except (TypeError, ValueError):
                continue
            if 1 <= local_index <= len(batch):
                verdicts[start + local_index - 1] = row

    kept: list[dict] = []
    rejected: list[dict] = []

    for index, question in enumerate(questions):
        verdict = verdicts.get(index)

        if verdict is None:
            # The checker never returned a verdict for this one. Keep it, but
            # be honest that it is unchecked.
            question["faithfulness_score"] = None
            question["verification_note"] = "Not verified — the checker returned no verdict"
            kept.append(question)
            continue

        try:
            score = float(verdict.get("faithfulness_score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))

        answerable = bool(verdict.get("answerable_from_sources"))
        answer_ok = bool(verdict.get("answer_matches_sources"))
        reason = str(verdict.get("reason") or "").strip()

        question["faithfulness_score"] = round(score, 3)

        if answerable and answer_ok and score >= settings.FAITHFULNESS_MIN_SCORE:
            question["verification_note"] = reason or "Grounded in the cited sources"
            kept.append(question)
        else:
            if not answerable:
                cause = "not answerable from the cited sources"
            elif not answer_ok:
                cause = "the marked answer does not match the sources (answer drift)"
            else:
                cause = f"faithfulness score {score:.2f} is below the {settings.FAITHFULNESS_MIN_SCORE} threshold"
            question["rejection_reason"] = f"{cause}. {reason}".strip()
            rejected.append(question)

    if rejected:
        logger.info(
            "Verification discarded %d/%d question(s)", len(rejected), len(questions)
        )
        for question in rejected:
            logger.debug(
                "  rejected: %s | %s",
                str(question.get("question_text"))[:70],
                question.get("rejection_reason"),
            )

    return kept, rejected


def _mark_unverified(questions: list[dict], note: str) -> list[dict]:
    for question in questions:
        question["faithfulness_score"] = None
        question["verification_note"] = note
    return questions


async def verify_faithfulness(
    question_text: str,
    correct_answer: str,
    source_texts: list[str],
) -> dict:
    """
    Verify a single question.

    Used when a teacher regenerates or edits one item and wants it re-checked
    without re-verifying the whole set.
    """
    settings = get_settings()
    fake_chunks = [
        SourceChunk(id=f"s{i}", text=text, source_type="notes")
        for i, text in enumerate(source_texts)
    ]
    question = {
        "question_text": question_text,
        "correct_answer": correct_answer,
        "question_type": "short_answer",
        "source_ids": [c.id for c in fake_chunks],
    }

    kept, rejected = await verify_question_set([question], fake_chunks)
    if kept:
        return {
            "is_faithful": True,
            "score": kept[0].get("faithfulness_score"),
            "answer_matches": True,
            "reason": kept[0].get("verification_note", ""),
        }
    reason = rejected[0].get("rejection_reason", "") if rejected else "Unknown"
    return {
        "is_faithful": False,
        "score": rejected[0].get("faithfulness_score") if rejected else 0.0,
        "answer_matches": False,
        "reason": reason,
    }


def summarise_verification(questions: list[dict]) -> Optional[str]:
    """One-line quality summary for the set banner, or None if nothing to say."""
    scored = [q["faithfulness_score"] for q in questions if q.get("faithfulness_score") is not None]
    if not scored:
        return None
    average = sum(scored) / len(scored)
    return (
        f"{len(scored)} of {len(questions)} question(s) verified against sources; "
        f"mean faithfulness {average:.2f}"
    )
