"""
Academix AI — RAG engine endpoints (PRD §8).

One engine behind two nav items:
  * Quiz Generation (student)  — instant practice, answer key, auto-marking.
  * Paper Style (teacher)      — exam draft bound to the course's Style
                                 Profile, with a mandatory review/approve gate.

Role separation is enforced by `authz.assert_can_use_mode` and
`authz.assert_set_access`: a student can neither request nor read Paper Style
output, nor reach the PYQ corpus (PRD §14).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.config import get_settings
from app.database import get_supabase_admin
from app.dependencies import CurrentUser, get_current_user, require_role
from app.models.rag import (
    AUTO_GRADED_TYPES,
    ChatRequest,
    ChatResponse,
    ChatSource,
    ContentDocumentResponse,
    CourseCorpusStatus,
    GeneratedQuestionResponse,
    GeneratedSetResponse,
    GenerationRequest,
    QuestionEditRequest,
    QuestionResult,
    QuizAnswerSubmit,
    QuizAttemptCreate,
    QuizAttemptResponse,
    RegenerateQuestionRequest,
    SetApprovalRequest,
    StyleProfileResponse,
)
from app.services import authz, notice_service
from app.services.rag import export, generation, retrieval, style_profile, verification
from app.services.rag.embeddings import provider_description
from app.services.rag.llm import LLMError

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Corpus readiness
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/corpus/{course_id}", response_model=CourseCorpusStatus)
async def get_corpus_status(
    course_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Whether a course has enough indexed material to generate from.

    The UI calls this before enabling the Generate button, so a user gets
    "upload some notes first" up front rather than a failed generation.
    """
    authz.assert_course_member(course_id, current_user)
    supabase = get_supabase_admin()

    documents = (
        supabase.table("content_documents")
        .select("status, source_type")
        .eq("course_id", course_id)
        .execute()
        .data
        or []
    )
    chunks = (
        supabase.table("content_chunks")
        .select("source_type")
        .eq("course_id", course_id)
        .limit(20000)
        .execute()
        .data
        or []
    )

    statuses = [d["status"] for d in documents]
    source_types = [c["source_type"] for c in chunks]

    status_payload = CourseCorpusStatus(
        course_id=course_id,
        total_documents=len(documents),
        indexed_documents=statuses.count("indexed"),
        failed_documents=statuses.count("failed"),
        pending_documents=statuses.count("pending") + statuses.count("processing"),
        total_chunks=len(chunks),
        notes_chunks=source_types.count("notes") + source_types.count("textbook"),
        pyq_chunks=source_types.count("pyq"),
    )

    # Students must not learn anything about the PYQ corpus (PRD §14).
    if current_user.role != "student":
        status_payload.pyq_questions = (
            supabase.table("pyq_questions")
            .select("id", count="exact")
            .eq("course_id", course_id)
            .execute()
            .count
            or 0
        )
        profiles = await style_profile.list_style_profiles(course_id)
        status_payload.has_internal_profile = any(
            p["exam_type"] == "internal" for p in profiles
        )
        status_payload.has_external_profile = any(
            p["exam_type"] == "external" for p in profiles
        )
    else:
        status_payload.pyq_chunks = 0

    status_payload.ready = status_payload.total_chunks > 0
    if not documents:
        status_payload.message = (
            "No material has been uploaded to this course yet. A teacher needs "
            "to add notes or slides in Classwork before questions can be generated."
        )
    elif status_payload.pending_documents and not status_payload.ready:
        status_payload.message = (
            f"{status_payload.pending_documents} document(s) are still being "
            f"indexed. This usually takes under a minute."
        )
    elif not status_payload.ready:
        status_payload.message = (
            "Material was uploaded but none of it could be indexed. Check the "
            "Classwork list for the reason on each file."
        )

    return status_payload


# ─────────────────────────────────────────────────────────────────────────────
# Conversational tutor (student chat) — routed RAG
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def chat_with_materials(
    data: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Grounded chat over a course's indexed materials, with a query router.

    Intents: quiz_practice, exam_prep, concept_explain, step_by_step,
    study_guidance, general_chat. Exam-prep uses Style Profile + PYQ *patterns*
    server-side; raw past papers are never returned (PRD §14).
    """
    from app.services.rag.query_router import route_query
    from app.services.rag import tutor as tutor_service

    authz.assert_course_member(data.course_id, current_user)

    message = data.message.strip()
    routed = await route_query(message)

    chunks_probe = await retrieval.sample_course_chunks(data.course_id, limit=1)
    ready = bool(chunks_probe)

    # Quiz / exam-prep that wants a generated set → open the form in the UI
    if routed.wants_quiz and routed.intent in ("quiz_practice", "exam_prep"):
        if routed.intent == "exam_prep":
            exam = routed.exam_type or "internal"
            reply = (
                f"Let's prep you for the **{exam}** exam using your notes"
                + (
                    " and this course's historical exam style."
                    if ready
                    else "."
                )
                + (
                    " Fill in the details below — I'll generate practice questions "
                    "that follow how this institute usually examines, without "
                    "copying past papers."
                    if ready
                    else " This course has no indexed material yet — ask your "
                    "teacher to upload notes in Classwork first."
                )
            )
        else:
            reply = (
                "Sure — I can build a practice quiz from your course materials. "
                "Fill in the details below and I'll generate it."
                if ready
                else "I'd love to generate a quiz, but this course has no indexed "
                "material yet. Ask your teacher to upload notes in Classwork first."
            )

        return ChatResponse(
            reply=reply,
            sources=[],
            intent=routed.intent,
            course_ready=ready,
            message=None if ready else "No indexed material for this course yet.",
            exam_type=routed.exam_type if routed.intent == "exam_prep" else None,
            topic_hints=routed.topic_hints,
            wants_quiz=True,
            router_confidence=routed.confidence,
        )

    if not ready:
        return ChatResponse(
            reply=(
                "I don't have any indexed notes for this course yet, so I can't "
                "answer from your syllabus. Ask your teacher to upload materials "
                "in Classwork, then try again."
            ),
            sources=[],
            intent=routed.intent,
            course_ready=False,
            message="No indexed material for this course yet.",
            exam_type=routed.exam_type,
            topic_hints=routed.topic_hints,
            wants_quiz=False,
            router_confidence=routed.confidence,
        )

    try:
        chunks = await retrieval.retrieve_chunks(
            query=message,
            course_id=data.course_id,
            source_type=None,  # notes+textbook preferred via merge; don't hard-filter
            top_k=10 if routed.intent == "step_by_step" else 8,
        )
        # Prefer non-PYQ chunks for student-visible grounding
        preferred = [c for c in chunks if c.source_type != "pyq"] or chunks
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    history = [{"role": h.role, "content": h.content} for h in data.history]

    try:
        reply, source_dicts, style_meta = await tutor_service.answer_routed(
            message=message,
            course_id=data.course_id,
            routed=routed,
            history=history,
            chunks=preferred,
        )
    except LLMError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"The tutor model was unreachable. {exc}",
        ) from exc

    return ChatResponse(
        reply=reply,
        sources=[ChatSource(**s) for s in source_dicts],
        intent=routed.intent,
        course_ready=True,
        exam_type=routed.exam_type,
        topic_hints=routed.topic_hints,
        wants_quiz=False,
        style_meta=style_meta,
        router_confidence=routed.confidence,
    )


@router.get("/documents/{course_id}", response_model=list[ContentDocumentResponse])
async def list_content_documents(
    course_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """The RAG corpus for a course, with ingestion status per document."""
    authz.assert_course_staff(course_id, current_user)
    result = (
        get_supabase_admin()
        .table("content_documents")
        .select("*")
        .eq("course_id", course_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


@router.post("/documents/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document(
    document_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """
    Retry ingestion for one document.

    Useful after a transient failure, or after switching embedding provider —
    vectors from a different model are not comparable and must be rebuilt.
    """
    from fastapi import BackgroundTasks  # local: only needed on this path

    supabase = get_supabase_admin()
    rows = (
        supabase.table("content_documents")
        .select("*")
        .eq("id", document_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    document = rows[0]
    authz.assert_course_staff(document["course_id"], current_user)

    import asyncio

    from app.services.rag.ingestion import ingest_document

    # Detached rather than a BackgroundTask: this endpoint returns 202 straight
    # away and the caller polls the document's status.
    asyncio.create_task(
        ingest_document(
            document_id=document_id,
            course_id=document["course_id"],
            file_url=document["file_url"],
            file_name=document["file_name"],
            source_type=document["source_type"],
            exam_type=document.get("exam_type"),
            year=document.get("year"),
        )
    )
    return {"status": "reindexing", "document_id": document_id}


# ─────────────────────────────────────────────────────────────────────────────
# Generation
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/generate", response_model=GeneratedSetResponse)
async def generate(
    data: GenerationRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Run the full RAG pipeline (PRD §8.2 Stages 3-5).

    Retrieve → (Paper Style) load style profile + exemplars → generate →
    verify → persist. Verification-rejected questions are dropped, and the
    reason is reported on the set rather than the count silently shrinking.
    """
    settings = get_settings()
    supabase = get_supabase_admin()

    authz.assert_can_use_mode(data.mode, data.course_id, current_user)

    if data.question_count > settings.MAX_QUESTIONS_PER_SET:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Ask for at most {settings.MAX_QUESTIONS_PER_SET} questions at a time.",
        )

    # 1. Retrieve grounding content (prefer notes/textbook for factual grounding).
    try:
        chunks = await retrieval.retrieve_chunks(
            query=data.retrieval_query(),
            course_id=data.course_id,
            top_k=max(settings.RETRIEVAL_TOP_K, data.question_count + 6),
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    if not chunks:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This course has no indexed material to generate from. A teacher "
            "needs to upload notes or slides in Classwork first.",
        )

    # Keep PYQ chunks out of the *factual* context for students; style comes
    # from exemplars separately. Teachers in Paper Style still get notes only
    # as facts — PYQs are pattern reference via exemplars.
    content_chunks = [c for c in chunks if c.source_type != "pyq"] or chunks

    # 2. Style Profile + PYQ exemplars for Paper Style OR student exam-prep.
    profile = None
    exemplars: list[dict] = []
    if data.exam_type and (data.mode == "paper_style" or data.style_aware):
        profile = await style_profile.get_style_profile(data.course_id, data.exam_type)
        exemplars = await retrieval.retrieve_pyq_exemplars(
            data.course_id, data.exam_type
        )

    # 3. Record the run so a failure is visible instead of vanishing.
    created = (
        supabase.table("generated_sets")
        .insert(
            {
                "requested_by": current_user.id,
                "course_id": data.course_id,
                "mode": data.mode,
                "exam_type": data.exam_type,
                "topic_tags": data.topic_tags,
                "difficulty": data.difficulty,
                "status": "generating",
                "generation_config": {
                    "question_types": data.question_types,
                    "requested_count": data.question_count,
                    "prompt": data.prompt,
                    "style_aware": data.style_aware,
                    "model": settings.GROQ_MODEL,
                    "embedding_provider": provider_description(),
                    "retrieved_chunks": len(content_chunks),
                    "style_profile_confidence": (profile or {}).get("confidence_score"),
                    "pyq_exemplars": len(exemplars),
                },
            }
        )
        .execute()
    )
    set_id = (created.data or [{}])[0].get("id")
    if not set_id:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not start the generation run"
        )

    try:
        # 4. Generate (PRD §8.2 Stage 4).
        questions = await generation.generate_questions(
            data, content_chunks, profile, exemplars
        )
        if not questions:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "No questions could be grounded in this course's material for "
                "those topics. Try broader topics, or upload more material.",
            )

        # 5. Verify (PRD §8.2 Stage 5).
        kept, rejected = await verification.verify_question_set(questions, content_chunks)
        if not kept:
            reasons = "; ".join(
                str(q.get("rejection_reason", ""))[:120] for q in rejected[:3]
            )
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Every generated question failed grounding verification and was "
                f"discarded rather than shown to you. Reasons: {reasons}",
            )

        # 6. Persist.
        records = []
        total_marks = 0
        for index, question in enumerate(kept, start=1):
            total_marks += int(question.get("marks") or 1)
            records.append(
                {
                    "set_id": set_id,
                    "question_text": question["question_text"],
                    "question_type": question["question_type"],
                    "options": question.get("options"),
                    "correct_answer": question["correct_answer"],
                    "explanation": question.get("explanation"),
                    "marks": question.get("marks") or 1,
                    "bloom_level": question.get("bloom_level"),
                    "section": question.get("section"),
                    "source_chunk_ids": question.get("source_ids") or [],
                    "source_texts": generation.serialise_sources(question, chunks),
                    "faithfulness_score": question.get("faithfulness_score"),
                    "verification_note": question.get("verification_note"),
                    "question_order": index,
                }
            )
        supabase.table("generated_questions").insert(records).execute()

        # 7. Format validation (PRD §8.2 Stage 5, third bullet).
        warnings: list[str] = []
        if data.mode == "paper_style":
            warnings = generation.validate_paper_format(kept, profile)
        if rejected:
            warnings.insert(
                0,
                f"{len(rejected)} generated question(s) were discarded for failing "
                f"grounding verification, so this set has {len(kept)} of the "
                f"{data.question_count} requested.",
            )
        summary = verification.summarise_verification(kept)
        if summary:
            warnings.append(summary)

        supabase.table("generated_sets").update(
            {
                # Both modes land as 'draft'; only Paper Style has an approve
                # step, but a quiz is equally not "approved" by anyone.
                "status": "draft",
                "total_questions": len(kept),
                "total_marks": total_marks,
                "error_message": None,
            }
        ).eq("id", set_id).execute()

    except HTTPException:
        supabase.table("generated_sets").update(
            {"status": "failed", "total_questions": 0}
        ).eq("id", set_id).execute()
        raise
    except LLMError as exc:
        supabase.table("generated_sets").update(
            {"status": "failed", "total_questions": 0, "error_message": str(exc)[:500]}
        ).eq("id", set_id).execute()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"The language model was unreachable, so nothing was generated. {exc}",
        ) from exc
    except Exception as exc:
        logger.exception("Generation failed for set %s", set_id)
        supabase.table("generated_sets").update(
            {"status": "failed", "total_questions": 0, "error_message": str(exc)[:500]}
        ).eq("id", set_id).execute()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Generation failed: {exc}"
        ) from exc

    result = await _load_set(set_id)
    result["warnings"] = warnings
    return result


@router.get("/sets", response_model=list[GeneratedSetResponse])
async def list_generated_sets(
    course_id: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    The caller's generation history.

    A teacher additionally sees Paper Style drafts by colleagues on courses
    they teach, so a set can be reviewed by whoever is on duty.
    """
    supabase = get_supabase_admin()
    query = supabase.table("generated_sets").select(
        "*, courses(name, code), profiles!generated_sets_requested_by_fkey(full_name)"
    )

    if current_user.role == "student":
        # Never expose Paper Style output to a student (PRD §14).
        query = query.eq("requested_by", current_user.id).eq("mode", "quiz_generation")
    elif current_user.role == "teacher":
        taught = authz.get_user_course_ids(current_user, role="teacher")
        clauses = [f"requested_by.eq.{current_user.id}"]
        if taught:
            clauses.append(f"course_id.in.({','.join(taught)})")
        query = query.or_(",".join(clauses))

    if course_id:
        query = query.eq("course_id", course_id)
    if mode:
        query = query.eq("mode", mode)

    result = query.order("created_at", desc=True).limit(limit).execute()

    sets = []
    for row in (result.data or []):
        course = row.pop("courses", None) or {}
        requester = row.pop("profiles!generated_sets_requested_by_fkey", None)
        if requester is None:
            requester = row.pop("profiles", None) or {}
        row["course_name"] = course.get("name")
        row["course_code"] = course.get("code")
        row["requester_name"] = (requester or {}).get("full_name")
        row["questions"] = []  # list view stays light; fetch the set for detail
        sets.append(row)
    return sets


@router.get("/sets/{set_id}", response_model=GeneratedSetResponse)
async def get_generated_set(
    set_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """One set with all its questions."""
    authz.assert_set_access(set_id, current_user)
    return await _load_set(set_id)


@router.get("/sets/{set_id}/export")
async def export_set_pdf(
    set_id: str,
    include_answers: bool = Query(True, description="Include the answer key"),
    include_sources: bool = Query(False, description="Include source citations"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Download a set as PDF (PRD §8.2 Stage 7).

    A draft is watermarked "NOT APPROVED FOR EXAM USE" so an exported draft can
    never be mistaken for a signed-off paper (PRD §14).
    """
    generated_set = authz.assert_set_access(set_id, current_user)
    full = await _load_set(set_id)

    if not full["questions"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This set has no questions to export."
        )

    try:
        pdf_bytes = export.render_question_set_pdf(
            generated_set,
            full["questions"],
            course_name=full.get("course_name") or "",
            course_code=full.get("course_code") or "",
            teacher_name=full.get("requester_name") or "",
            include_answers=include_answers,
            include_sources=include_sources,
        )
    except Exception as exc:
        logger.exception("PDF export failed for set %s", set_id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Could not build the PDF: {exc}"
        ) from exc

    filename = export.suggested_filename(generated_set, full.get("course_code") or "")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_set(
    set_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Delete a generated set.

    An approved Paper Style set is immutable (PRD §13 Auditability: "Every
    approved Paper Style set is versioned and immutable once locked").
    """
    generated_set = authz.assert_set_access(set_id, current_user)

    if generated_set["mode"] == "paper_style":
        if generated_set["status"] == "approved":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "An approved paper set is locked for audit and cannot be deleted.",
            )
        authz.assert_set_access(set_id, current_user, require_staff=True)

    get_supabase_admin().table("generated_sets").delete().eq("id", set_id).execute()


# ─────────────────────────────────────────────────────────────────────────────
# Teacher review (PRD §8.2 Stage 6)
# ─────────────────────────────────────────────────────────────────────────────


@router.patch(
    "/sets/{set_id}/questions/{question_id}", response_model=GeneratedQuestionResponse
)
async def edit_question(
    set_id: str,
    question_id: str,
    data: QuestionEditRequest,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """Edit one question in a draft."""
    generated_set = authz.assert_set_access(set_id, current_user, require_staff=True)
    _assert_editable(generated_set)

    supabase = get_supabase_admin()
    question = _load_question(question_id, set_id)

    updates = data.model_dump(exclude_none=True)
    updates["teacher_edited"] = True

    # A teacher's own wording has not been machine-verified, so drop the stale
    # score rather than let an edited question keep the original's credibility.
    if "question_text" in updates or "correct_answer" in updates:
        updates["faithfulness_score"] = None
        updates["verification_note"] = "Edited by a teacher after verification"

    result = (
        supabase.table("generated_questions")
        .update(updates)
        .eq("id", question_id)
        .eq("set_id", set_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")

    _recalculate_totals(set_id)
    return result.data[0]


@router.post(
    "/sets/{set_id}/questions/{question_id}/regenerate",
    response_model=GeneratedQuestionResponse,
)
async def regenerate_question(
    set_id: str,
    question_id: str,
    data: RegenerateQuestionRequest,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """
    Replace one question with a fresh one (PRD §8.2 Stage 6).

    The replacement is generated against the same course material and told
    which questions already exist, so it does not duplicate the rest of the set.
    """
    settings = get_settings()
    supabase = get_supabase_admin()

    generated_set = authz.assert_set_access(set_id, current_user, require_staff=True)
    _assert_editable(generated_set)
    question = _load_question(question_id, set_id)

    siblings = (
        supabase.table("generated_questions")
        .select("question_text")
        .eq("set_id", set_id)
        .neq("id", question_id)
        .execute()
        .data
        or []
    )

    config = generated_set.get("generation_config") or {}
    request = GenerationRequest(
        course_id=generated_set["course_id"],
        mode=generated_set["mode"],
        exam_type=generated_set.get("exam_type"),
        topic_tags=generated_set.get("topic_tags") or [],
        difficulty=generated_set.get("difficulty") or "medium",
        question_count=1,
        question_types=config.get("question_types") or [question["question_type"]],
    )

    try:
        chunks = await retrieval.retrieve_chunks(
            query=request.retrieval_query() or question["question_text"],
            course_id=request.course_id,
            top_k=settings.RETRIEVAL_TOP_K,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    if not chunks:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No indexed material is available to regenerate from."
        )

    profile = None
    if request.mode == "paper_style" and request.exam_type:
        profile = await style_profile.get_style_profile(request.course_id, request.exam_type)

    try:
        replacement = await generation.regenerate_single_question(
            request=request,
            context_chunks=chunks,
            existing_questions=[s["question_text"] for s in siblings],
            instruction=data.instruction,
            style_profile=profile,
        )
    except LLMError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"The model was unreachable: {exc}"
        ) from exc

    if not replacement:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Could not produce a distinct replacement question from this material.",
        )

    kept, _ = await verification.verify_question_set([replacement], chunks)
    if not kept:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The replacement failed grounding verification, so the original "
            "question was left in place.",
        )
    replacement = kept[0]

    result = (
        supabase.table("generated_questions")
        .update(
            {
                "question_text": replacement["question_text"],
                "question_type": replacement["question_type"],
                "options": replacement.get("options"),
                "correct_answer": replacement["correct_answer"],
                "explanation": replacement.get("explanation"),
                "marks": replacement.get("marks") or question["marks"],
                "bloom_level": replacement.get("bloom_level"),
                # Keep the original section so the paper's structure holds.
                "section": question.get("section") or replacement.get("section"),
                "source_chunk_ids": replacement.get("source_ids") or [],
                "source_texts": generation.serialise_sources(replacement, chunks),
                "faithfulness_score": replacement.get("faithfulness_score"),
                "verification_note": replacement.get("verification_note"),
                "teacher_edited": False,
            }
        )
        .eq("id", question_id)
        .execute()
    )

    _recalculate_totals(set_id)
    return result.data[0]


@router.delete(
    "/sets/{set_id}/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_question(
    set_id: str,
    question_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """Remove a question from a draft and renumber the rest."""
    supabase = get_supabase_admin()
    generated_set = authz.assert_set_access(set_id, current_user, require_staff=True)
    _assert_editable(generated_set)
    _load_question(question_id, set_id)

    supabase.table("generated_questions").delete().eq("id", question_id).eq(
        "set_id", set_id
    ).execute()

    # Close the gap so Q1..Qn stays contiguous in the UI and the PDF.
    remaining = (
        supabase.table("generated_questions")
        .select("id")
        .eq("set_id", set_id)
        .order("question_order")
        .execute()
        .data
        or []
    )
    for index, row in enumerate(remaining, start=1):
        supabase.table("generated_questions").update({"question_order": index}).eq(
            "id", row["id"]
        ).execute()

    _recalculate_totals(set_id)


@router.post("/sets/{set_id}/approve", response_model=GeneratedSetResponse)
async def approve_set(
    set_id: str,
    data: SetApprovalRequest,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """
    Approve or reject a Paper Style draft (PRD §8.2 Stage 6).

    Approval locks the set: it becomes immutable and auditable (PRD §13). A set
    can only be approved once — re-approving would silently move the audit
    timestamp.
    """
    generated_set = authz.assert_set_access(set_id, current_user, require_staff=True)

    if generated_set["mode"] != "paper_style":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only Paper Style sets go through the review gate.",
        )
    if generated_set["status"] == "approved":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This set is already approved and locked.",
        )

    supabase = get_supabase_admin()

    if data.status == "approved":
        count = (
            supabase.table("generated_questions")
            .select("id", count="exact")
            .eq("set_id", set_id)
            .execute()
            .count
            or 0
        )
        if count == 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "An empty set cannot be approved."
            )

    updates: dict = {"status": data.status}
    if data.status == "approved":
        updates["approved_by"] = current_user.id
        updates["approved_at"] = datetime.now(timezone.utc).isoformat()

    supabase.table("generated_sets").update(updates).eq("id", set_id).execute()

    course = authz.assert_course_exists(generated_set["course_id"])
    await notice_service.create_system_notice(
        title=f"Paper draft {data.status}: {course['code']}",
        body=(
            f"{current_user.full_name} {data.status} a "
            f"{generated_set.get('exam_type') or ''} paper draft for "
            f"{course['name']}."
        ),
        notice_type="admin",
        posted_by=current_user.id,
        # Audit trail for staff only — students must not learn that an exam
        # paper was approved (PRD §14).
        target_roles=["admin", "teacher"],
    )

    return await _load_set(set_id)


# ─────────────────────────────────────────────────────────────────────────────
# Quiz attempts (student)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/attempts", response_model=QuizAttemptResponse, status_code=status.HTTP_201_CREATED)
async def start_quiz_attempt(
    data: QuizAttemptCreate,
    current_user: CurrentUser = Depends(require_role("student")),
):
    """
    Begin an attempt at a generated quiz.

    Reuses an existing in-progress attempt rather than creating a second one,
    so a page reload does not fork the student's answers across two rows.
    """
    supabase = get_supabase_admin()
    generated_set = authz.assert_set_access(data.set_id, current_user)

    if generated_set["mode"] != "quiz_generation":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This set is not a practice quiz.")

    existing = (
        supabase.table("student_quiz_attempts")
        .select("*")
        .eq("set_id", data.set_id)
        .eq("student_id", current_user.id)
        .eq("status", "in_progress")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )

    attempt = (
        existing[0]
        if existing
        else (
            supabase.table("student_quiz_attempts")
            .insert(
                {"student_id": current_user.id, "set_id": data.set_id, "status": "in_progress"}
            )
            .execute()
            .data
            or [{}]
        )[0]
    )

    attempt["questions"] = _load_questions(data.set_id, hide_answers=True)
    attempt["results"] = []
    return attempt


@router.post("/attempts/{attempt_id}/submit", response_model=QuizAttemptResponse)
async def submit_quiz_attempt(
    attempt_id: str,
    data: QuizAnswerSubmit,
    current_user: CurrentUser = Depends(require_role("student")),
):
    """
    Submit and auto-mark an attempt (PRD §8.2 Stage 7).

    Objective types (MCQ, true/false, fill-in-the-blank) are marked
    automatically. Written answers are self-assessed against the model answer,
    so they are excluded from the score denominator — reporting 4/20 because
    sixteen marks were unmarkable would misrepresent the result.
    """
    supabase = get_supabase_admin()
    attempt = authz.assert_attempt_access(attempt_id, current_user)

    if attempt["status"] == "submitted":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This attempt has already been submitted."
        )

    questions = _load_questions(attempt["set_id"], hide_answers=False)
    if not questions:
        raise HTTPException(status.HTTP_409_CONFLICT, "This quiz has no questions.")

    results: list[QuestionResult] = []
    auto_marks_available = 0
    auto_marks_earned = 0.0
    total_marks = 0

    for question in questions:
        marks = int(question.get("marks") or 1)
        total_marks += marks
        given = (data.answers.get(question["id"]) or "").strip()
        expected = (question.get("correct_answer") or "").strip()
        auto = question["question_type"] in AUTO_GRADED_TYPES

        is_correct: Optional[bool] = None
        awarded = 0.0

        if auto:
            auto_marks_available += marks
            is_correct = _answers_match(given, expected, question)
            if is_correct:
                awarded = marks
                auto_marks_earned += marks

        results.append(
            QuestionResult(
                question_id=question["id"],
                student_answer=given or None,
                correct_answer=expected,
                is_correct=is_correct,
                auto_graded=auto,
                marks=marks,
                awarded=awarded,
            )
        )

    updated = (
        supabase.table("student_quiz_attempts")
        .update(
            {
                "answers": data.answers,
                "score": auto_marks_earned,
                "total_marks": total_marks,
                "auto_graded_marks": auto_marks_available,
                "time_spent_seconds": data.time_spent_seconds,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "status": "submitted",
            }
        )
        .eq("id", attempt_id)
        .execute()
    )

    payload = (updated.data or [attempt])[0]
    payload["questions"] = questions
    payload["results"] = [r.model_dump() for r in results]
    return payload


@router.get("/attempts", response_model=list[QuizAttemptResponse])
async def list_quiz_attempts(
    course_id: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The caller's quiz history."""
    supabase = get_supabase_admin()
    query = (
        supabase.table("student_quiz_attempts")
        .select("*, generated_sets(course_id, mode, topic_tags, courses(name, code))")
        .eq("student_id", current_user.id)
        .order("started_at", desc=True)
        .limit(limit)
    )

    attempts = []
    for row in (query.execute().data or []):
        generated_set = row.pop("generated_sets", None) or {}
        if course_id and generated_set.get("course_id") != course_id:
            continue
        course = generated_set.get("courses") or {}
        row["course_name"] = course.get("name")
        row["topic_tags"] = generated_set.get("topic_tags") or []
        row["questions"] = []
        row["results"] = []
        attempts.append(row)
    return attempts


@router.get("/attempts/{attempt_id}", response_model=QuizAttemptResponse)
async def get_quiz_attempt(
    attempt_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Review a past attempt, with answers revealed once submitted."""
    attempt = authz.assert_attempt_access(attempt_id, current_user)
    submitted = attempt["status"] == "submitted"
    questions = _load_questions(attempt["set_id"], hide_answers=not submitted)

    attempt["questions"] = questions
    attempt["results"] = []

    if submitted:
        answers = attempt.get("answers") or {}
        results = []
        for question in questions:
            marks = int(question.get("marks") or 1)
            given = (answers.get(question["id"]) or "").strip()
            expected = (question.get("correct_answer") or "").strip()
            auto = question["question_type"] in AUTO_GRADED_TYPES
            is_correct = _answers_match(given, expected, question) if auto else None
            results.append(
                QuestionResult(
                    question_id=question["id"],
                    student_answer=given or None,
                    correct_answer=expected,
                    is_correct=is_correct,
                    auto_graded=auto,
                    marks=marks,
                    awarded=float(marks) if is_correct else 0.0,
                ).model_dump()
            )
        attempt["results"] = results

    return attempt


# ─────────────────────────────────────────────────────────────────────────────
# Style profiles (teacher only — PRD §14)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/style-profile/{course_id}", response_model=list[StyleProfileResponse])
async def list_style_profiles(
    course_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """Every style profile for a course."""
    authz.assert_can_read_pyq_corpus(course_id, current_user)
    return await style_profile.list_style_profiles(course_id)


@router.get("/style-profile/{course_id}/{exam_type}", response_model=StyleProfileResponse)
async def get_style_profile(
    course_id: str,
    exam_type: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    authz.assert_can_read_pyq_corpus(course_id, current_user)
    profile = await style_profile.get_style_profile(course_id, exam_type)
    if not profile:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No {exam_type} style profile yet. Upload previous-year papers for "
            f"this course (tagged as PYQ with the exam type) and one will be "
            f"built automatically.",
        )
    return profile


@router.post(
    "/style-profile/{course_id}/{exam_type}/recompute",
    response_model=StyleProfileResponse,
)
async def recompute_style_profile(
    course_id: str,
    exam_type: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """Rebuild a style profile from the current PYQ data."""
    authz.assert_can_read_pyq_corpus(course_id, current_user)

    if exam_type not in ("internal", "external"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "exam_type must be 'internal' or 'external'"
        )

    profile = await style_profile.compute_style_profile(course_id, exam_type)
    if not profile:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Not enough {exam_type} question data to build a profile "
            f"(at least {style_profile.MIN_QUESTIONS} extracted questions are "
            f"needed). Upload more previous-year papers.",
        )
    return profile


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _assert_editable(generated_set: dict) -> None:
    if generated_set["status"] == "approved":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This set is approved and locked for audit. Reject it first, or "
            "generate a new draft.",
        )


def _load_question(question_id: str, set_id: str) -> dict:
    rows = (
        get_supabase_admin()
        .table("generated_questions")
        .select("*")
        .eq("id", question_id)
        .eq("set_id", set_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    return rows[0]


def _load_questions(set_id: str, hide_answers: bool = False) -> list[dict]:
    """
    Questions for a set.

    `hide_answers` blanks the answer key while a quiz is still in progress —
    otherwise the correct answers are sitting in the network response the
    student can simply read.
    """
    rows = (
        get_supabase_admin()
        .table("generated_questions")
        .select("*")
        .eq("set_id", set_id)
        .order("question_order")
        .execute()
        .data
        or []
    )

    if hide_answers:
        for row in rows:
            row["correct_answer"] = ""
            row["explanation"] = None
    return rows


def _recalculate_totals(set_id: str) -> None:
    """Keep the set's question and marks totals in step after an edit."""
    supabase = get_supabase_admin()
    rows = (
        supabase.table("generated_questions")
        .select("marks")
        .eq("set_id", set_id)
        .execute()
        .data
        or []
    )
    supabase.table("generated_sets").update(
        {
            "total_questions": len(rows),
            "total_marks": sum(int(r.get("marks") or 0) for r in rows),
        }
    ).eq("id", set_id).execute()


def _answers_match(given: str, expected: str, question: dict) -> bool:
    """
    Compare a student's answer with the key.

    MCQ answers are stored as a bare option letter by
    `generation._normalise_mcq`, but the UI may submit either the letter or the
    full option text, so accept both. Fill-in-the-blank is compared
    case- and punctuation-insensitively; anything stricter fails on a trailing
    full stop.
    """
    if not given:
        return False

    given_clean = given.strip().lower()
    expected_clean = expected.strip().lower()

    if question["question_type"] == "mcq":
        if given_clean == expected_clean:
            return True
        # The student sent the whole option, e.g. "B) Chlorophyll".
        options = question.get("options") or []
        for option in options:
            letter = str(option)[:1].upper()
            if letter == expected.strip().upper():
                body = str(option)[2:].strip().lower() if len(str(option)) > 2 else ""
                return given_clean in (str(option).strip().lower(), body)
        return False

    if question["question_type"] == "true_false":
        truthy = {"true", "t", "yes"}
        falsy = {"false", "f", "no"}
        if expected_clean in truthy:
            return given_clean in truthy
        if expected_clean in falsy:
            return given_clean in falsy
        return given_clean == expected_clean

    # fill_blank
    import re

    normalise = lambda text: re.sub(r"[^a-z0-9 ]", "", text).strip()  # noqa: E731
    return normalise(given_clean) == normalise(expected_clean)


async def _load_set(set_id: str) -> dict:
    """A set with its course, requester and questions."""
    supabase = get_supabase_admin()
    rows = (
        supabase.table("generated_sets")
        .select("*, courses(name, code), profiles!generated_sets_requested_by_fkey(full_name)")
        .eq("id", set_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generated set not found")

    result = rows[0]
    course = result.pop("courses", None) or {}
    requester = result.pop("profiles!generated_sets_requested_by_fkey", None)
    if requester is None:
        requester = result.pop("profiles", None) or {}

    result["course_name"] = course.get("name")
    result["course_code"] = course.get("code")
    result["requester_name"] = (requester or {}).get("full_name")
    result["questions"] = _load_questions(set_id)
    result.setdefault("warnings", [])
    return result
