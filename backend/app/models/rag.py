"""
Academix AI — RAG engine schemas.

Covers content documents, generation requests, generated sets/questions,
student quiz attempts, and style profiles (PRD §8.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

QuestionType = Literal["mcq", "short_answer", "long_answer", "true_false", "fill_blank"]
BloomLevel = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
GenerationMode = Literal["quiz_generation", "paper_style"]
ExamType = Literal["internal", "external"]
Difficulty = Literal["easy", "medium", "hard"]

# Objective types the platform can mark without a human. Short/long answers are
# self-assessed against a model answer (PRD §8.2 Stage 7).
AUTO_GRADED_TYPES: frozenset[str] = frozenset({"mcq", "true_false", "fill_blank"})


# ── Content documents ────────────────────────────────────────────────────────

class ContentDocumentResponse(BaseModel):
    id: str
    course_id: str
    uploaded_by: str
    material_id: Optional[str] = None
    file_url: str
    file_name: str
    file_size: Optional[int] = None
    source_type: str
    exam_type: Optional[str] = None
    year: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    page_count: Optional[int] = None
    chunk_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Generation request ───────────────────────────────────────────────────────

class GenerationRequest(BaseModel):
    """Parameters for a Quiz Generation or Paper Style run (PRD §8.1 input 3)."""

    course_id: str
    mode: GenerationMode
    topic_tags: list[str] = Field(default_factory=list)
    # Paper Style: required. Quiz Generation: optional — set when the student
    # is doing exam-prep practice so we can apply the Style Profile + PYQ patterns.
    exam_type: Optional[ExamType] = None
    difficulty: Difficulty = "medium"
    question_count: int = Field(default=10, ge=1, le=50)
    question_types: list[QuestionType] = Field(default_factory=lambda: ["mcq", "short_answer"])
    # Free-text steer from the Gemini-style prompt box, e.g.
    # "focus on the trade-offs between the two scheduling algorithms".
    prompt: Optional[str] = Field(default=None, max_length=1000)
    # When true (student exam prep), generation obeys the course Style Profile
    # and PYQ phrasing patterns without switching into Paper Style / teacher review.
    style_aware: bool = False

    @field_validator("topic_tags")
    @classmethod
    def _clean_topics(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        cleaned: list[str] = []
        for value in values:
            topic = (value or "").strip()
            key = topic.lower()
            if topic and key not in seen:
                seen.add(key)
                cleaned.append(topic)
        return cleaned[:12]

    @field_validator("question_types")
    @classmethod
    def _at_least_one_type(cls, values: list[str]) -> list[str]:
        unique = list(dict.fromkeys(values))
        if not unique:
            raise ValueError("Select at least one question type")
        return unique

    @model_validator(mode="after")
    def _exam_type_rules(self) -> "GenerationRequest":
        if self.mode == "paper_style":
            if not self.exam_type:
                raise ValueError("exam_type is required for Paper Style (internal or external)")
            self.style_aware = True
        elif self.mode == "quiz_generation":
            if self.style_aware and not self.exam_type:
                raise ValueError(
                    "exam_type (internal or external) is required for style-aware exam prep"
                )
            if not self.style_aware:
                # Casual practice quizzes must not silently inherit an exam filter.
                self.exam_type = None
        return self

    def retrieval_query(self) -> str:
        """The text used to retrieve grounding chunks."""
        parts: list[str] = []
        if self.prompt:
            parts.append(self.prompt.strip())
        parts.extend(self.topic_tags)
        if self.style_aware and self.exam_type:
            parts.append(f"{self.exam_type} exam")
        return " ".join(p for p in parts if p).strip()


# ── Generated output ─────────────────────────────────────────────────────────

class GeneratedQuestionResponse(BaseModel):
    id: str
    set_id: str
    question_text: str
    question_type: str
    options: Optional[list[str]] = None
    correct_answer: str
    explanation: Optional[str] = None
    marks: int = 1
    bloom_level: Optional[str] = None
    section: Optional[str] = None
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_texts: list[dict[str, Any]] = Field(default_factory=list)
    faithfulness_score: Optional[float] = None
    verification_note: Optional[str] = None
    teacher_edited: bool = False
    question_order: int = 0

    @field_validator("source_texts", mode="before")
    @classmethod
    def _normalise_sources(cls, value: Any) -> list[dict[str, Any]]:
        """
        Accept both the current shape and the flat list of strings written by
        earlier builds, so existing rows still render in the sources panel.
        """
        if not value:
            return []
        if isinstance(value, list):
            normalised: list[dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    normalised.append(item)
                elif isinstance(item, str):
                    normalised.append({"text": item})
            return normalised
        return []


class GeneratedSetResponse(BaseModel):
    id: str
    requested_by: str
    course_id: str
    mode: str
    exam_type: Optional[str] = None
    topic_tags: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    status: str
    total_marks: Optional[int] = None
    total_questions: Optional[int] = None
    generation_config: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    # Joined for display
    course_name: Optional[str] = None
    course_code: Optional[str] = None
    requester_name: Optional[str] = None
    questions: list[GeneratedQuestionResponse] = Field(default_factory=list)
    # Set-level quality summary, computed rather than stored.
    warnings: list[str] = Field(default_factory=list)


class QuestionEditRequest(BaseModel):
    """A teacher's edit to one generated question (PRD §8.2 Stage 6)."""

    question_text: Optional[str] = None
    options: Optional[list[str]] = None
    correct_answer: Optional[str] = None
    marks: Optional[int] = Field(default=None, ge=1, le=100)
    explanation: Optional[str] = None
    section: Optional[str] = None
    bloom_level: Optional[BloomLevel] = None

    @model_validator(mode="after")
    def _not_empty(self) -> "QuestionEditRequest":
        if not self.model_dump(exclude_none=True):
            raise ValueError("Provide at least one field to update")
        return self


class SetApprovalRequest(BaseModel):
    """Approve or reject a Paper Style draft."""

    status: Literal["approved", "rejected"]


class RegenerateQuestionRequest(BaseModel):
    """Ask for one question to be replaced (keeps the rest of the set intact)."""

    instruction: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional steer, e.g. 'make it numerical' or 'harder'.",
    )


# ── Quiz attempts ────────────────────────────────────────────────────────────

class QuizAttemptCreate(BaseModel):
    set_id: str


class QuizAnswerSubmit(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    time_spent_seconds: Optional[int] = Field(default=None, ge=0)


class QuestionResult(BaseModel):
    """Per-question marking outcome returned after a quiz is submitted."""

    question_id: str
    student_answer: Optional[str] = None
    correct_answer: str
    is_correct: Optional[bool] = None  # None for self-assessed written answers
    auto_graded: bool
    marks: int
    awarded: float


class QuizAttemptResponse(BaseModel):
    id: str
    student_id: str
    set_id: str
    answers: dict[str, Any] = Field(default_factory=dict)
    score: Optional[float] = None
    total_marks: Optional[int] = None
    auto_graded_marks: Optional[int] = None
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    time_spent_seconds: Optional[int] = None
    status: str = "in_progress"
    # Joined for display
    course_name: Optional[str] = None
    topic_tags: list[str] = Field(default_factory=list)
    questions: list[GeneratedQuestionResponse] = Field(default_factory=list)
    results: list[QuestionResult] = Field(default_factory=list)


class ManualStyleProfileRequest(BaseModel):
    course_id: str
    exam_type: ExamType
    total_marks: int = Field(default=30, ge=1)
    duration_minutes: int = Field(default=60, ge=1)
    passing_marks: Optional[int] = None
    instructions: Optional[str] = None
    section_structure: list[dict[str, Any]] = Field(default_factory=list)
    bloom_distribution: dict[str, float] = Field(default_factory=dict)


class ManualQuestionInput(BaseModel):
    question_text: str
    question_type: QuestionType = "short_answer"
    marks: int = Field(default=2, ge=1)
    section: Optional[str] = None
    options: Optional[list[str]] = None
    correct_answer: Optional[str] = None
    bloom_level: Optional[str] = "understand"
    topic_tag: Optional[str] = None


class ManualPaperSetRequest(BaseModel):
    course_id: str
    exam_type: ExamType = "internal"
    title: Optional[str] = "Manual Question Paper"
    total_marks: int = Field(default=30, ge=1)
    duration_minutes: int = Field(default=60, ge=1)
    status: Literal["draft", "approved"] = "draft"
    instructions: Optional[str] = None
    section_structure: list[dict[str, Any]] = Field(default_factory=list)
    questions: list[ManualQuestionInput] = Field(default_factory=list)


# ── Style profile ────────────────────────────────────────────────────────────

class StyleProfileResponse(BaseModel):
    id: str
    course_id: str
    exam_type: str
    total_marks: Optional[int] = None
    duration_minutes: Optional[int] = None
    section_structure: list[dict[str, Any]] = Field(default_factory=list)
    bloom_distribution: dict[str, float] = Field(default_factory=dict)
    common_patterns: dict[str, Any] = Field(default_factory=dict)
    question_count: int = 0
    confidence_score: float = 0.0
    pyq_count: int = 0
    last_computed_at: Optional[datetime] = None

    @property
    def is_low_confidence(self) -> bool:
        """PRD §15: flag profiles built from too few PYQs."""
        return self.confidence_score < 0.5


# ── Sources panel ────────────────────────────────────────────────────────────

class SourceChunk(BaseModel):
    """One retrieved chunk, as cited in the NotebookLM-style sources panel."""

    id: str
    text: str
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    page_ref: Optional[str] = None
    source_type: str = "notes"
    topic_tag: Optional[str] = None
    similarity: Optional[float] = None
    hybrid_score: Optional[float] = None

    def citation(self) -> str:
        """Short human-readable provenance label."""
        label = self.document_name or "Unknown document"
        return f"{label} · {self.page_ref}" if self.page_ref else label


class CourseCorpusStatus(BaseModel):
    """Whether a course has enough indexed material to generate from."""

    course_id: str
    total_documents: int = 0
    indexed_documents: int = 0
    failed_documents: int = 0
    pending_documents: int = 0
    total_chunks: int = 0
    notes_chunks: int = 0
    pyq_chunks: int = 0
    pyq_questions: int = 0
    has_internal_profile: bool = False
    has_external_profile: bool = False
    ready: bool = False
    message: Optional[str] = None


# ── Conversational tutor (Quiz Generation chat) ──────────────────────────────

class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    course_id: str
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=12)


class ChatSource(BaseModel):
    document_name: Optional[str] = None
    page_ref: Optional[str] = None
    text: str
    source_type: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    sources: list[ChatSource] = Field(default_factory=list)
    intent: Literal[
        "quiz_practice",
        "exam_prep",
        "concept_explain",
        "step_by_step",
        "study_guidance",
        "general_chat",
        # legacy alias kept so older clients keep working
        "quiz",
        "chat",
    ] = "general_chat"
    course_ready: bool = False
    message: Optional[str] = None  # corpus status hint when not ready
    exam_type: Optional[ExamType] = None
    topic_hints: list[str] = Field(default_factory=list)
    wants_quiz: bool = False
    style_meta: Optional[dict[str, Any]] = None
    router_confidence: Optional[float] = None
