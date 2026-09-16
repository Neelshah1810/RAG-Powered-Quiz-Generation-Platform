"""
Academix AI — PDF export for generated question sets (PRD §8.2 Stage 7).

"Teacher: structured in-app draft, exportable as PDF in v1."

Renders an approved (or draft) Paper Style set as an exam-paper-shaped PDF,
optionally with an answer key and the per-question source citations that PRD
§13 requires an approved set to carry ("a full source-citation trail per
question").

Uses fpdf2 — pure Python, so it works on machines without a native toolchain.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# fpdf2's built-in Helvetica is Latin-1 only. Rather than bundle a Unicode TTF,
# transliterate the handful of characters that realistically show up in
# generated text (smart quotes, dashes, common symbols) and drop the rest.
_TRANSLITERATIONS = {
    "‘": "'", "’": "'", "‚": ",", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "--", "−": "-", "‐": "-", "‑": "-",
    "…": "...", " ": " ", "​": "", "•": "-",
    "×": "x", "÷": "/", "≤": "<=", "≥": ">=",
    "≠": "!=", "≈": "~=", "√": "sqrt", "∞": "inf",
    "→": "->", "←": "<-", "⇒": "=>", "∑": "sum",
    "∏": "prod", "∆": "delta", "∂": "d",
}


def _latin1(text: Any) -> str:
    """Make text safe for fpdf2's core fonts without mangling it."""
    if text is None:
        return ""
    text = str(text)
    for source, replacement in _TRANSLITERATIONS.items():
        text = text.replace(source, replacement)
    # Greek letters and similar survive as their names rather than vanishing.
    text = unicodedata.normalize("NFKD", text)
    out: list[str] = []
    for char in text:
        if ord(char) < 256:
            out.append(char)
        elif unicodedata.combining(char):
            continue  # accents already folded by NFKD
        else:
            name = unicodedata.name(char, "")
            if name.startswith("GREEK SMALL LETTER "):
                out.append(name.removeprefix("GREEK SMALL LETTER ").lower())
            elif name.startswith("GREEK CAPITAL LETTER "):
                out.append(name.removeprefix("GREEK CAPITAL LETTER ").capitalize())
            else:
                out.append("?")
    result = "".join(out)
    # Collapse the runs of '?' a formula-heavy question can produce.
    return re.sub(r"\?{3,}", "...", result)


class _PaperPDF:
    """Thin wrapper over fpdf2 with the paper's header/footer conventions."""

    def __init__(self, title: str, subtitle: str, watermark: Optional[str]) -> None:
        from fpdf import FPDF

        self.title = _latin1(title)
        self.subtitle = _latin1(subtitle)
        self.watermark = _latin1(watermark) if watermark else None

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.set_margins(18, 16, 18)
        pdf.set_title(self.title)
        pdf.set_creator("Academix AI")
        self.pdf = pdf

    # ── primitives ───────────────────────────────────────────────────────────

    @property
    def usable_width(self) -> float:
        return self.pdf.w - self.pdf.l_margin - self.pdf.r_margin

    def text_block(self, text: str, size: int = 11, style: str = "", height: float = 5.6) -> None:
        self.pdf.set_font("Helvetica", style, size)
        self.pdf.multi_cell(self.usable_width, height, _latin1(text))

    def spacer(self, height: float = 3.0) -> None:
        self.pdf.ln(height)

    def rule(self) -> None:
        y = self.pdf.get_y() + 1
        self.pdf.set_draw_color(190, 190, 190)
        self.pdf.line(self.pdf.l_margin, y, self.pdf.w - self.pdf.r_margin, y)
        self.pdf.ln(4)

    # ── layout ───────────────────────────────────────────────────────────────

    def cover(self, meta_rows: list[tuple[str, str]]) -> None:
        pdf = self.pdf
        pdf.add_page()

        if self.watermark:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(200, 60, 40)
            pdf.cell(0, 6, self.watermark, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)

        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(self.usable_width, 8, self.title, align="C")

        if self.subtitle:
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(90, 90, 90)
            pdf.multi_cell(self.usable_width, 6, self.subtitle, align="C")
            pdf.set_text_color(0, 0, 0)

        pdf.ln(3)
        self.rule()

        pdf.set_font("Helvetica", "", 10)
        for label, value in meta_rows:
            if not value:
                continue
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(38, 5.6, _latin1(f"{label}:"))
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(self.usable_width - 38, 5.6, _latin1(value))
        self.rule()

    def section_heading(self, label: str) -> None:
        # Don't leave a heading stranded at the foot of a page.
        if self.pdf.get_y() > self.pdf.h - 45:
            self.pdf.add_page()
        self.spacer(2)
        self.pdf.set_font("Helvetica", "B", 12)
        self.pdf.set_fill_color(240, 242, 245)
        self.pdf.cell(
            self.usable_width, 8, _latin1(f"  {label}"),
            fill=True, new_x="LMARGIN", new_y="NEXT",
        )
        self.spacer(2)

    def question(self, number: int, question: dict, show_answers: bool, show_sources: bool) -> None:
        pdf = self.pdf

        marks = question.get("marks") or 1
        body = question.get("question_text") or ""

        # Question number, text, and a right-aligned marks tag on one line.
        pdf.set_font("Helvetica", "B", 11)
        number_width = 11.0
        pdf.cell(number_width, 5.8, f"Q{number}.")

        marks_label = f"[{marks} {'mark' if marks == 1 else 'marks'}]"
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(
            self.usable_width - number_width - 24, 5.8, _latin1(body),
            new_x="RIGHT", new_y="TOP",
        )
        after_text_y = pdf.get_y()

        pdf.set_font("Helvetica", "I", 9)
        pdf.set_xy(pdf.w - pdf.r_margin - 24, after_text_y)
        pdf.cell(24, 5.8, marks_label, align="R", new_x="LMARGIN", new_y="NEXT")

        # MCQ options, indented.
        options = question.get("options") or []
        if options:
            pdf.set_font("Helvetica", "", 10.5)
            for option in options:
                pdf.set_x(pdf.l_margin + number_width)
                pdf.multi_cell(self.usable_width - number_width, 5.2, _latin1(option))

        if show_answers:
            answer = question.get("correct_answer") or ""
            pdf.set_x(pdf.l_margin + number_width)
            pdf.set_font("Helvetica", "B", 9.5)
            pdf.set_text_color(15, 110, 70)
            pdf.multi_cell(self.usable_width - number_width, 5, _latin1(f"Answer: {answer}"))
            explanation = question.get("explanation")
            if explanation:
                pdf.set_x(pdf.l_margin + number_width)
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(70, 70, 70)
                pdf.multi_cell(
                    self.usable_width - number_width, 4.6,
                    _latin1(f"Why: {explanation}"),
                )
            pdf.set_text_color(0, 0, 0)

        # Metadata line: cognitive level and verification state.
        tags: list[str] = []
        if question.get("bloom_level"):
            tags.append(f"Bloom: {question['bloom_level']}")
        score = question.get("faithfulness_score")
        if score is not None:
            tags.append(f"Faithfulness: {float(score):.2f}")
        if question.get("teacher_edited"):
            tags.append("Teacher-edited")
        if tags:
            pdf.set_x(pdf.l_margin + number_width)
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(130, 130, 130)
            pdf.multi_cell(self.usable_width - number_width, 4, _latin1(" | ".join(tags)))
            pdf.set_text_color(0, 0, 0)

        if show_sources:
            for source in question.get("source_texts") or []:
                if not isinstance(source, dict):
                    continue
                label = source.get("document_name") or "Source"
                if source.get("page_ref"):
                    label += f", {source['page_ref']}"
                excerpt = (source.get("text") or "")[:260].replace("\n", " ")
                pdf.set_x(pdf.l_margin + number_width)
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(110, 110, 130)
                pdf.multi_cell(
                    self.usable_width - number_width, 4,
                    _latin1(f"Source - {label}: {excerpt}..."),
                )
                pdf.set_text_color(0, 0, 0)

        self.spacer(3.5)

    def output(self) -> bytes:
        return bytes(self.pdf.output())


def _group_by_section(questions: list[dict]) -> list[tuple[Optional[str], list[dict]]]:
    """
    Group questions by their section label, preserving question order.

    Returns `[(None, [...])]` when no question carries a section, so a quiz
    (which has no section structure) renders as one flat list.
    """
    if not any(q.get("section") for q in questions):
        return [(None, questions)]

    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for question in questions:
        label = str(question.get("section") or "Unassigned")
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(question)

    # "Unassigned" last; the rest alphabetically, matching how papers are printed.
    ordered = sorted(k for k in order if k != "Unassigned")
    if "Unassigned" in order:
        ordered.append("Unassigned")
    return [(label, groups[label]) for label in ordered]


def render_question_set_pdf(
    generated_set: dict,
    questions: list[dict],
    *,
    course_name: str = "",
    course_code: str = "",
    teacher_name: str = "",
    include_answers: bool = True,
    include_sources: bool = True,
) -> bytes:
    """
    Render a generated set to PDF bytes.

    A draft carries a prominent "NEEDS REVIEW" watermark — PRD §8.2 Stage 6 and
    §14 make the draft/approved gate mandatory, so an exported draft must never
    be mistakable for a signed-off paper.
    """
    mode = generated_set.get("mode")
    status = generated_set.get("status", "draft")
    exam_type = generated_set.get("exam_type")

    if mode == "paper_style":
        title = f"{course_code or course_name} - {(exam_type or 'Internal').title()} Examination"
        subtitle = course_name if course_code else ""
    else:
        title = f"Practice Quiz - {course_name or 'Course'}"
        subtitle = course_code

    watermark = (
        None
        if status == "approved"
        else "DRAFT - NOT APPROVED FOR EXAM USE - REQUIRES TEACHER REVIEW"
    )

    document = _PaperPDF(title=title, subtitle=subtitle, watermark=watermark)

    total_marks = generated_set.get("total_marks") or sum(
        int(q.get("marks") or 0) for q in questions
    )
    topics = generated_set.get("topic_tags") or []
    generated_at = generated_set.get("created_at")
    if isinstance(generated_at, str):
        generated_at = generated_at.replace("Z", "")[:16].replace("T", " ")

    meta: list[tuple[str, str]] = [
        ("Questions", str(len(questions))),
        ("Total marks", str(total_marks)),
        ("Difficulty", str(generated_set.get("difficulty") or "").title()),
        ("Topics", ", ".join(str(t) for t in topics) if topics else "All course topics"),
        ("Status", "Approved" if status == "approved" else "Draft - needs review"),
        ("Prepared by", teacher_name),
        ("Generated", str(generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))),
    ]
    document.cover(meta)

    if mode == "paper_style":
        document.text_block(
            "All questions below were generated from this course's own uploaded "
            "material and are grounded in the cited sources. They remain a draft "
            "until a teacher approves the set.",
            size=9,
            style="I",
        )
        document.spacer(2)

    number = 1
    for section_label, section_questions in _group_by_section(questions):
        if section_label:
            marks_in_section = sum(int(q.get("marks") or 0) for q in section_questions)
            document.section_heading(
                f"Section {section_label}  ({len(section_questions)} questions, {marks_in_section} marks)"
            )
        for question in section_questions:
            document.question(
                number, question,
                show_answers=include_answers,
                show_sources=include_sources,
            )
            number += 1

    return document.output()


def suggested_filename(generated_set: dict, course_code: str = "") -> str:
    """A safe, descriptive download filename."""
    mode = "paper" if generated_set.get("mode") == "paper_style" else "quiz"
    exam = generated_set.get("exam_type") or ""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    parts = [p for p in (course_code, mode, exam, stamp) if p]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", "-".join(parts)).strip("-").lower()
    return f"{stem or 'academix-question-set'}.pdf"
