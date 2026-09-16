"""
Tests for the student quiz generation endpoint (/api/rag/quiz/generate).

These are *schema-level* tests that verify request/response shapes, model
conversion, and validation — they do NOT require a running Supabase or LLM.
Integration tests that hit the live endpoint are in e2e_test.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.rag import (
    GenerationRequest,
    QuizGenerationRequest,
)


# ── QuizGenerationRequest model ─────────────────────────────────────────────


class TestQuizGenerationRequest:
    """Unit tests for the simplified quiz request model."""

    def test_defaults(self):
        req = QuizGenerationRequest(course_id="course-abc")
        assert req.course_id == "course-abc"
        assert req.topic_tags == []
        assert req.question_count == 5
        assert req.difficulty == "medium"
        assert req.question_types == ["mcq", "short_answer"]
        assert req.prompt is None

    def test_custom_values(self):
        req = QuizGenerationRequest(
            course_id="c1",
            topic_tags=["sorting", "trees"],
            question_count=10,
            difficulty="hard",
            question_types=["mcq"],
            prompt="Focus on red-black trees",
        )
        assert req.topic_tags == ["sorting", "trees"]
        assert req.question_count == 10
        assert req.difficulty == "hard"
        assert req.question_types == ["mcq"]
        assert req.prompt == "Focus on red-black trees"

    def test_question_count_bounds(self):
        """question_count must be 1..50."""
        with pytest.raises(ValidationError):
            QuizGenerationRequest(course_id="c1", question_count=0)
        with pytest.raises(ValidationError):
            QuizGenerationRequest(course_id="c1", question_count=51)

    def test_invalid_difficulty(self):
        with pytest.raises(ValidationError):
            QuizGenerationRequest(course_id="c1", difficulty="nightmare")

    def test_invalid_question_type(self):
        with pytest.raises(ValidationError):
            QuizGenerationRequest(course_id="c1", question_types=["essay"])


# ── to_generation_request conversion ────────────────────────────────────────


class TestToGenerationRequest:
    """Verify that QuizGenerationRequest.to_generation_request() builds
    a correct full GenerationRequest with the right mode & style_aware flags."""

    def test_mode_is_quiz_generation(self):
        req = QuizGenerationRequest(course_id="c1").to_generation_request()
        assert isinstance(req, GenerationRequest)
        assert req.mode == "quiz_generation"

    def test_style_aware_is_false(self):
        req = QuizGenerationRequest(course_id="c1").to_generation_request()
        assert req.style_aware is False

    def test_exam_type_is_none(self):
        """Casual quizzes should never carry an exam_type filter."""
        req = QuizGenerationRequest(course_id="c1").to_generation_request()
        assert req.exam_type is None

    def test_fields_propagate(self):
        quiz_req = QuizGenerationRequest(
            course_id="c1",
            topic_tags=["sorting"],
            question_count=8,
            difficulty="hard",
            question_types=["mcq", "true_false"],
            prompt="focus on quicksort",
        )
        gen_req = quiz_req.to_generation_request()
        assert gen_req.course_id == "c1"
        assert gen_req.topic_tags == ["sorting"]
        assert gen_req.question_count == 8
        assert gen_req.difficulty == "hard"
        assert gen_req.question_types == ["mcq", "true_false"]
        assert gen_req.prompt == "focus on quicksort"

    def test_retrieval_query_from_converted(self):
        """The converted request should produce a meaningful retrieval query."""
        gen_req = QuizGenerationRequest(
            course_id="c1",
            topic_tags=["merge sort", "heaps"],
            prompt="advanced examples",
        ).to_generation_request()
        query = gen_req.retrieval_query()
        assert "advanced examples" in query
        assert "merge sort" in query
        assert "heaps" in query
        # style_aware=False, so no standalone 'exam' keyword injected
        # (note: 'exam' appears inside 'examples', so check the phrase)
        assert "internal exam" not in query.lower()
        assert "external exam" not in query.lower()
