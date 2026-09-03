"""
Academix AI — Query router for the student RAG tutor.

Classifies each student message into one intent so retrieval, prompting and
UI behaviour can specialise:

  quiz_practice   — casual practice quiz from notes
  exam_prep       — prepare for Internal/External; uses Style Profile + PYQ
                    *patterns* (never exposes raw past papers to the student)
  concept_explain — explain a concept from the notes
  step_by_step    — worked solution / reasoning walkthrough
  study_guidance  — what to revise, how to prepare, study plan
  general_chat    — open grounded Q&A

Routing is rule-first (fast, deterministic) with an optional LLM tie-break
when the message is ambiguous. Exam type (internal/external) and topic hints
are extracted in the same pass.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from app.services.rag.llm import LLMError, complete_json

logger = logging.getLogger(__name__)

Intent = Literal[
    "quiz_practice",
    "exam_prep",
    "concept_explain",
    "step_by_step",
    "study_guidance",
    "general_chat",
]

ExamTypeHint = Literal["internal", "external"]

_QUIZ = re.compile(
    r"\b(quiz|practice\s*(test|quiz|questions?)|generate\s*(a\s*)?(quiz|questions?|test)|"
    r"make\s*(a\s*)?(quiz|test)|give\s*me\s*(a\s*)?(quiz|test|questions?)|"
    r"test\s*me|mcqs?|true\s*/?\s*false|fill\s*in\s*the\s*blank)\b",
    re.I,
)
_EXAM = re.compile(
    r"\b(internal|external|mid[\s-]?sem|end[\s-]?sem|final\s*exam|semester\s*exam|"
    r"exam\s*prep|prepare\s*for|upcoming\s*exam|likely\s*(to\s*)?appear|"
    r"previous\s*year|pyq|past\s*paper|exam\s*style|exam\s*pattern)\b",
    re.I,
)
_INTERNAL = re.compile(r"\b(internal|mid[\s-]?sem|midterm|unit\s*test|sessional)\b", re.I)
_EXTERNAL = re.compile(
    r"\b(external|end[\s-]?sem|final\s*exam|university\s*exam|board\s*exam)\b", re.I
)
_EXPLAIN = re.compile(
    r"\b(explain|what\s+is|what\s+are|define|describe|meaning\s+of|concept\s+of|"
    r"tell\s+me\s+about|help\s+me\s+understand|clarify)\b",
    re.I,
)
_STEPS = re.compile(
    r"\b(step\s*by\s*step|walk\s*me\s*through|how\s+(do|to|can)\s+i|"
    r"derive|solve|calculate|compute|prove|work\s*(ed|ing)?\s*solution|"
    r"show\s*(me\s*)?(the\s*)?steps|reasoning)\b",
    re.I,
)
_GUIDANCE = re.compile(
    r"\b(what\s+should\s+i\s+(study|revise|prepare)|study\s*plan|revision\s*plan|"
    r"how\s+should\s+i\s+prepare|important\s+topics|focus\s+on|"
    r"what\s+to\s+revise|guidance|roadmap)\b",
    re.I,
)
_TOPIC_SPLIT = re.compile(r"[,;/]| and | & ", re.I)


@dataclass
class RoutedQuery:
    """Result of routing one student utterance."""

    intent: Intent
    exam_type: Optional[ExamTypeHint] = None
    topic_hints: list[str] = field(default_factory=list)
    wants_quiz: bool = False
    confidence: float = 0.5
    rationale: str = ""

    @property
    def style_aware(self) -> bool:
        """True when generation should obey the course Style Profile."""
        return self.intent == "exam_prep" or (
            self.wants_quiz and self.exam_type is not None
        )


def _extract_exam_type(text: str) -> Optional[ExamTypeHint]:
    has_internal = bool(_INTERNAL.search(text))
    has_external = bool(_EXTERNAL.search(text))
    if has_internal and not has_external:
        return "internal"
    if has_external and not has_internal:
        return "external"
    if has_internal and has_external:
        # Prefer the last mentioned.
        last_i = max(m.end() for m in _INTERNAL.finditer(text))
        last_e = max(m.end() for m in _EXTERNAL.finditer(text))
        return "external" if last_e >= last_i else "internal"
    if _EXAM.search(text):
        # "exam prep" without qualifier → default internal (more common mid-term ask)
        return "internal"
    return None


def _extract_topics(text: str) -> list[str]:
    """
    Light topic extraction from phrases like "on sorting and trees".

    Deliberately conservative — empty is fine; the quiz form still lets the
    student type topics explicitly.
    """
    hints: list[str] = []
    patterns = [
        r"(?:on|about|regarding|covering|for)\s+([A-Za-z0-9][\w\s\-]{2,60}?)(?:\?|$|,|\.|please|for\s+(?:my|the))",
        r"topics?\s*[:=]\s*([A-Za-z0-9][\w\s,\-/]{2,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        raw = match.group(1).strip(" .,:;")
        for part in _TOPIC_SPLIT.split(raw):
            topic = part.strip(" .,:;")
            if 2 < len(topic) < 48 and topic.lower() not in {
                "the exam", "my exam", "internal", "external", "quiz", "test",
            }:
                hints.append(topic)
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for h in hints:
        key = h.lower()
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out[:6]


def route_query_rules(message: str) -> RoutedQuery:
    """Deterministic first-pass router."""
    text = (message or "").strip()
    exam_type = _extract_exam_type(text)
    topics = _extract_topics(text)
    wants_quiz = bool(_QUIZ.search(text))

    if wants_quiz and (exam_type or _EXAM.search(text)):
        return RoutedQuery(
            intent="exam_prep",
            exam_type=exam_type or "internal",
            topic_hints=topics,
            wants_quiz=True,
            confidence=0.9,
            rationale="quiz + exam cue",
        )

    if _EXAM.search(text) and not wants_quiz:
        # "help me prepare for internal" without explicitly asking for a quiz
        return RoutedQuery(
            intent="exam_prep",
            exam_type=exam_type or "internal",
            topic_hints=topics,
            wants_quiz=True,  # exam prep usually surfaces the quiz form
            confidence=0.85,
            rationale="exam preparation request",
        )

    if wants_quiz:
        return RoutedQuery(
            intent="quiz_practice",
            exam_type=None,
            topic_hints=topics,
            wants_quiz=True,
            confidence=0.9,
            rationale="practice quiz request",
        )

    if _GUIDANCE.search(text):
        return RoutedQuery(
            intent="study_guidance",
            exam_type=exam_type,
            topic_hints=topics,
            wants_quiz=False,
            confidence=0.85,
            rationale="study guidance cue",
        )

    if _STEPS.search(text):
        return RoutedQuery(
            intent="step_by_step",
            exam_type=exam_type,
            topic_hints=topics,
            wants_quiz=False,
            confidence=0.85,
            rationale="step-by-step / solve cue",
        )

    if _EXPLAIN.search(text):
        return RoutedQuery(
            intent="concept_explain",
            exam_type=exam_type,
            topic_hints=topics,
            wants_quiz=False,
            confidence=0.8,
            rationale="concept explanation cue",
        )

    return RoutedQuery(
        intent="general_chat",
        exam_type=exam_type,
        topic_hints=topics,
        wants_quiz=False,
        confidence=0.45,
        rationale="fallback general chat",
    )


_ROUTER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "exam_type", "topic_hints", "wants_quiz", "confidence"],
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "quiz_practice",
                "exam_prep",
                "concept_explain",
                "step_by_step",
                "study_guidance",
                "general_chat",
            ],
        },
        "exam_type": {"type": ["string", "null"], "enum": ["internal", "external"]},
        "topic_hints": {"type": "array", "items": {"type": "string"}},
        "wants_quiz": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
}


async def route_query(message: str, *, use_llm_fallback: bool = True) -> RoutedQuery:
    """
    Route a student message.

    Rules handle the common cases. When confidence is low and
    `use_llm_fallback` is on, a small classifier confirms the intent.
    """
    routed = route_query_rules(message)
    if routed.confidence >= 0.75 or not use_llm_fallback:
        return routed

    try:
        parsed = complete_json(
            system=(
                "You classify student messages for a college RAG tutor. "
                "Pick exactly one intent. exam_type is internal/external/null. "
                "topic_hints are short syllabus topics if mentioned. "
                "wants_quiz is true if they want generated practice questions."
            ),
            user=f"Message: {message.strip()[:800]}",
            temperature=0.0,
            max_tokens=256,
            json_schema=_ROUTER_SCHEMA,
            schema_name="route",
        )
        if not isinstance(parsed, dict):
            return routed

        intent = parsed.get("intent") or routed.intent
        if intent not in {
            "quiz_practice",
            "exam_prep",
            "concept_explain",
            "step_by_step",
            "study_guidance",
            "general_chat",
        }:
            intent = routed.intent

        exam = parsed.get("exam_type")
        if exam not in ("internal", "external", None):
            exam = routed.exam_type

        topics = parsed.get("topic_hints") or routed.topic_hints
        if not isinstance(topics, list):
            topics = routed.topic_hints
        topics = [str(t).strip() for t in topics if str(t).strip()][:6]

        wants = bool(parsed.get("wants_quiz", routed.wants_quiz))
        if intent == "exam_prep":
            wants = True
            exam = exam or routed.exam_type or "internal"

        conf = float(parsed.get("confidence") or 0.7)
        return RoutedQuery(
            intent=intent,  # type: ignore[arg-type]
            exam_type=exam,  # type: ignore[arg-type]
            topic_hints=topics,
            wants_quiz=wants,
            confidence=max(conf, routed.confidence),
            rationale="llm+rules",
        )
    except (LLMError, Exception) as exc:
        logger.info("LLM router fallback skipped: %s", exc)
        return routed
