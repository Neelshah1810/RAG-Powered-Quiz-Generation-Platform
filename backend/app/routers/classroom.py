"""
Academix AI — Classroom endpoints (PRD §9, Google Classroom parity).

Stream · Materials · Assignments · Submissions · Grading · People.

Material upload is the integration point with the RAG engine: every upload
creates a `content_documents` row and schedules ingestion (PRD §9, "Every
upload auto-triggers RAG ingestion … directly feeding both Quiz Generation and
Paper Style").
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.config import get_settings
from app.database import get_supabase_admin
from app.dependencies import CurrentUser, get_current_user, require_role
from app.models.classroom import (
    AnnouncementCreate,
    AnnouncementResponse,
    AssignmentCreate,
    AssignmentResponse,
    AssignmentUpdate,
    DownloadResponse,
    GradeCreate,
    GradeResponse,
    MaterialResponse,
    StreamItem,
    SubmissionResponse,
)
from app.services import (
    authz,
    classroom_service,
    course_service,
    notice_service,
    scheduler_service,
    storage_service,
)
from app.services.rag.ingestion import ingest_document

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Stream
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{course_id}/stream", response_model=list[StreamItem])
async def get_stream(
    course_id: str,
    limit: int = Query(50, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The course home feed."""
    authz.assert_course_member(course_id, current_user)
    return await classroom_service.get_course_stream(course_id, limit)


# ─────────────────────────────────────────────────────────────────────────────
# Announcements
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{course_id}/announcements", response_model=list[AnnouncementResponse])
async def list_announcements(
    course_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    authz.assert_course_member(course_id, current_user)
    return await classroom_service.list_announcements(course_id)


@router.post(
    "/{course_id}/announcements",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_announcement(
    course_id: str,
    data: AnnouncementCreate,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    course = authz.assert_course_staff(course_id, current_user)

    announcement = await classroom_service.create_announcement(
        course_id, current_user.id, data.text, data.attachment_urls
    )

    await notice_service.create_system_notice(
        title=f"New announcement in {course['name']}",
        body=data.text[:400],
        notice_type="announcement",
        course_id=course_id,
        posted_by=current_user.id,
        send_email=True,
    )

    announcement["author_name"] = current_user.full_name
    return announcement


@router.delete(
    "/{course_id}/announcements/{announcement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_announcement(
    course_id: str,
    announcement_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    authz.assert_course_staff(course_id, current_user)
    await classroom_service.delete_announcement(announcement_id)


# ─────────────────────────────────────────────────────────────────────────────
# Materials
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{course_id}/materials", response_model=list[MaterialResponse])
async def list_materials(
    course_id: str,
    topic_tag: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Course material, with live RAG ingestion status.

    Students do not see the PYQ corpus (PRD §14: "Students never see … the raw
    PYQ corpus"), so PYQ-sourced material is filtered out for them.
    """
    authz.assert_course_member(course_id, current_user)
    materials = await classroom_service.list_materials(course_id, topic_tag)

    if current_user.role == "student":
        materials = [m for m in materials if m.get("source_type") != "pyq"]

    return materials


@router.get("/{course_id}/topics", response_model=list[str])
async def list_topics(
    course_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Topic tags in use on this course, for filters and generation presets."""
    authz.assert_course_member(course_id, current_user)
    return await classroom_service.list_topics(course_id)


@router.post(
    "/{course_id}/materials",
    response_model=MaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_material(
    course_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    topic_tag: Optional[str] = Form(None),
    source_type: str = Form("notes"),
    exam_type: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """
    Upload course material and index it for the RAG engine.

    The order here matters: the file is stored *first*, and the database rows
    are only written once the upload actually succeeded. The earlier version
    swallowed storage failures and saved a record pointing at a non-existent
    `local/...` path, which then failed at ingestion time with a confusing
    error and left an undownloadable material in the Classwork list.
    """
    settings = get_settings()
    course = authz.assert_course_staff(course_id, current_user)

    if source_type not in ("notes", "textbook", "pyq"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "source_type must be 'notes', 'textbook' or 'pyq'",
        )
    if exam_type and exam_type not in ("internal", "external"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "exam_type must be 'internal' or 'external'"
        )
    if source_type == "pyq" and not exam_type:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A previous-year paper needs an exam type (internal or external) so "
            "it can feed the right style profile.",
        )

    file_name = file.filename or "upload"
    file_bytes = await file.read()
    storage_service.assert_upload_allowed(file_name, len(file_bytes))

    bucket = settings.BUCKET_PYQ if source_type == "pyq" else settings.BUCKET_MATERIALS
    key = storage_service.build_object_key(course_id, file_name=file_name)

    try:
        file_url = storage_service.upload_bytes(
            bucket, key, file_bytes, file.content_type
        )
    except storage_service.StorageError as exc:
        logger.error("Material upload failed for course %s: %s", course_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"The file could not be saved to storage, so nothing was recorded. {exc}",
        ) from exc

    supabase = get_supabase_admin()

    # Create the RAG document row first so the material can point at it and the
    # Classwork list can show ingestion status immediately.
    document = (
        supabase.table("content_documents")
        .insert(
            {
                "course_id": course_id,
                "uploaded_by": current_user.id,
                "file_url": file_url,
                "file_name": file_name,
                "file_size": len(file_bytes),
                "source_type": source_type,
                "exam_type": exam_type,
                "year": year,
                "status": "pending",
            }
        )
        .execute()
    )
    document_id = (document.data or [{}])[0].get("id")

    try:
        material = await classroom_service.create_material(
            course_id=course_id,
            uploaded_by=current_user.id,
            title=title,
            file_url=file_url,
            file_name=file_name,
            file_size=len(file_bytes),
            description=description,
            topic_tag=topic_tag,
            document_id=document_id,
        )
    except Exception as exc:
        # Don't leave an orphaned document row (or file) behind.
        if document_id:
            supabase.table("content_documents").delete().eq("id", document_id).execute()
        storage_service.delete_object(file_url, bucket)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Could not save the material record: {exc}",
        ) from exc

    if document_id:
        supabase.table("content_documents").update({"material_id": material["id"]}).eq(
            "id", document_id
        ).execute()

        background_tasks.add_task(
            ingest_document,
            document_id=document_id,
            course_id=course_id,
            file_url=file_url,
            file_name=file_name,
            source_type=source_type,
            exam_type=exam_type,
            year=year,
        )

    material["ingestion_status"] = "pending"
    material["source_type"] = source_type
    material["exam_type"] = exam_type
    material["year"] = year
    material["uploader_name"] = current_user.full_name
    material["chunk_count"] = 0

    # A PYQ paper is teacher-only material; announcing it to students would
    # tell them an exam paper had been loaded (PRD §14).
    if source_type != "pyq":
        await notice_service.create_system_notice(
            title=f"New material in {course['name']}: {title}",
            body=description or f"A new {source_type} file has been posted.",
            notice_type="material",
            course_id=course_id,
            posted_by=current_user.id,
            send_email=True,
        )

    return material


@router.get(
    "/{course_id}/materials/{material_id}/download",
    response_model=DownloadResponse,
)
async def download_material(
    course_id: str,
    material_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    A short-lived signed URL for a material file.

    Buckets are private, so this is the only way to read one — and it is issued
    only after the enrollment check passes.
    """
    settings = get_settings()
    authz.assert_course_member(course_id, current_user)

    material = await classroom_service.get_material(material_id, course_id)
    if not material:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Material not found")

    # Block a student from pulling a PYQ paper by its direct URL.
    if current_user.role == "student" and material.get("document_id"):
        document = (
            get_supabase_admin()
            .table("content_documents")
            .select("source_type")
            .eq("id", material["document_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        if document and document[0].get("source_type") == "pyq":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Material not found")

    try:
        url = storage_service.create_signed_url(
            material["file_url"],
            settings.BUCKET_MATERIALS,
            download_name=material.get("file_name"),
        )
    except storage_service.StorageError as exc:
        logger.error("Could not sign material %s: %s", material_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "This file is not available for download. It may have been removed "
            "from storage.",
        ) from exc

    return DownloadResponse(
        download_url=url,
        file_name=material.get("file_name") or "download",
        expires_in_seconds=settings.SIGNED_URL_TTL_SECONDS,
    )


@router.delete(
    "/{course_id}/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_material(
    course_id: str,
    material_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """Remove a material, its file, and its chunks from the RAG index."""
    settings = get_settings()
    authz.assert_course_staff(course_id, current_user)

    material = await classroom_service.get_material(material_id, course_id)
    if not material:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Material not found")

    await classroom_service.delete_material(material_id)
    storage_service.delete_object(material["file_url"], settings.BUCKET_MATERIALS)


# ─────────────────────────────────────────────────────────────────────────────
# Assignments
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{course_id}/assignments", response_model=list[AssignmentResponse])
async def list_assignments(
    course_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Assignments for a course.

    A student gets their own submission state per assignment; a teacher gets
    submission and graded counts against the enrolled student total.
    """
    authz.assert_course_member(course_id, current_user)

    if current_user.role == "student":
        return await classroom_service.list_assignments(
            course_id, student_id=current_user.id
        )

    expected = await course_service.count_course_students(course_id)
    return await classroom_service.list_assignments(
        course_id, expected_student_count=expected
    )


@router.post(
    "/{course_id}/assignments",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    course_id: str,
    data: AssignmentCreate,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    course = authz.assert_course_staff(course_id, current_user)

    assignment = await classroom_service.create_assignment(
        course_id=course_id,
        created_by=current_user.id,
        title=data.title,
        instructions=data.instructions,
        attachment_urls=data.attachment_urls,
        due_at=data.due_at.isoformat() if data.due_at else None,
        max_points=data.max_points,
        topic_tag=data.topic_tag,
    )

    # PRD §10: assignment due dates auto-populate the Scheduler.
    await scheduler_service.sync_assignment_due_event(assignment, current_user.id)

    due_note = (
        f" Due {data.due_at.strftime('%d %b %Y, %H:%M')}." if data.due_at else ""
    )
    await notice_service.create_system_notice(
        title=f"New assignment in {course['name']}: {data.title}",
        body=f"Worth {data.max_points} points.{due_note}",
        notice_type="assignment",
        course_id=course_id,
        posted_by=current_user.id,
        send_email=True,
    )

    assignment["author_name"] = current_user.full_name
    assignment["submission_count"] = 0
    assignment["graded_count"] = 0
    return assignment


@router.get(
    "/{course_id}/assignments/{assignment_id}", response_model=AssignmentResponse
)
async def get_assignment(
    course_id: str,
    assignment_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    authz.assert_course_member(course_id, current_user)
    authz.assert_assignment_in_course(assignment_id, course_id)

    assignment = await classroom_service.get_assignment(assignment_id)
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    if current_user.role == "student":
        submission = await classroom_service.get_student_submission(
            assignment_id, current_user.id
        )
        grade = (submission or {}).get("grade") or {}
        assignment["my_status"] = (
            submission["status"]
            if submission
            else ("missing" if assignment.get("is_overdue") else "not_submitted")
        )
        assignment["my_submitted_at"] = (submission or {}).get("submitted_at")
        assignment["my_points"] = grade.get("points_awarded")
        assignment["my_feedback"] = grade.get("feedback_text")

    return assignment


@router.patch(
    "/{course_id}/assignments/{assignment_id}", response_model=AssignmentResponse
)
async def update_assignment(
    course_id: str,
    assignment_id: str,
    data: AssignmentUpdate,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    authz.assert_course_staff(course_id, current_user)
    authz.assert_assignment_in_course(assignment_id, course_id)

    updates = data.model_dump(exclude_none=True, exclude={"clear_due_date"})

    if data.clear_due_date:
        # `update_assignment` strips None values, so a due date is cleared with
        # an explicit write rather than by passing None through.
        updates.pop("due_at", None)
        get_supabase_admin().table("assignments").update({"due_at": None}).eq(
            "id", assignment_id
        ).execute()

    if updates:
        await classroom_service.update_assignment(assignment_id, updates)

    assignment = await classroom_service.get_assignment(assignment_id)
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    # Keep the calendar marker in step with the (possibly new) due date.
    await scheduler_service.sync_assignment_due_event(assignment, current_user.id)
    return assignment


@router.delete(
    "/{course_id}/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_assignment(
    course_id: str,
    assignment_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """Delete an assignment; submissions, grades and its due-date event cascade."""
    authz.assert_course_staff(course_id, current_user)
    authz.assert_assignment_in_course(assignment_id, course_id)
    await classroom_service.delete_assignment(assignment_id)


# ─────────────────────────────────────────────────────────────────────────────
# Submissions
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/{course_id}/assignments/{assignment_id}/submit",
    response_model=SubmissionResponse,
)
async def submit_assignment(
    course_id: str,
    assignment_id: str,
    file: Optional[UploadFile] = File(None),
    text_response: Optional[str] = Form(None),
    current_user: CurrentUser = Depends(require_role("student")),
):
    """
    Turn in an assignment (PRD §9, "Turn-in / Submission").

    A file, a typed response, or both. Late work is accepted and flagged rather
    than refused. Re-submitting before grading replaces the previous attempt.
    """
    settings = get_settings()
    authz.assert_course_member(course_id, current_user)
    authz.assert_assignment_in_course(assignment_id, course_id)

    has_text = bool((text_response or "").strip())
    if file is None and not has_text:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Attach a file or type a response before submitting.",
        )

    existing = await classroom_service.get_student_submission(
        assignment_id, current_user.id
    )
    if existing and existing["status"] == "graded":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This assignment has already been graded and can no longer be "
            "resubmitted. Ask your teacher to reopen it.",
        )

    file_url = None
    file_name = None
    if file is not None and file.filename:
        file_bytes = await file.read()
        storage_service.assert_submission_upload_allowed(file.filename, len(file_bytes))
        key = storage_service.build_object_key(
            assignment_id, current_user.id, file_name=file.filename
        )
        try:
            file_url = storage_service.upload_bytes(
                settings.BUCKET_SUBMISSIONS,
                key,
                file_bytes,
                file.content_type,
                upsert=True,
            )
            file_name = file.filename
        except storage_service.StorageError as exc:
            logger.error("Submission upload failed for %s: %s", current_user.id, exc)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"Your file could not be uploaded, so nothing was submitted. {exc}",
            ) from exc

    submission = await classroom_service.create_submission(
        assignment_id=assignment_id,
        student_id=current_user.id,
        file_url=file_url,
        file_name=file_name,
        text_response=(text_response or "").strip() or None,
    )
    submission["student_name"] = current_user.full_name
    submission["student_email"] = current_user.email
    submission["grade"] = None
    return submission


@router.post(
    "/{course_id}/assignments/{assignment_id}/unsubmit",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unsubmit_assignment(
    course_id: str,
    assignment_id: str,
    current_user: CurrentUser = Depends(require_role("student")),
):
    """Withdraw a submission so it can be redone. Refused once graded."""
    authz.assert_course_member(course_id, current_user)
    authz.assert_assignment_in_course(assignment_id, course_id)

    if not await classroom_service.unsubmit(assignment_id, current_user.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "There is nothing to withdraw, or the work has already been graded.",
        )


@router.get(
    "/{course_id}/assignments/{assignment_id}/submissions",
    response_model=list[SubmissionResponse],
)
async def list_submissions(
    course_id: str,
    assignment_id: str,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """
    The grading list for one assignment.

    Includes enrolled students who have *not* submitted, so the teacher can see
    who is missing — matching Google Classroom's behaviour.
    """
    authz.assert_course_staff(course_id, current_user)
    authz.assert_assignment_in_course(assignment_id, course_id)
    return await classroom_service.list_submissions(assignment_id, course_id)


@router.get(
    "/{course_id}/assignments/{assignment_id}/my-submission",
    response_model=Optional[SubmissionResponse],
)
async def get_my_submission(
    course_id: str,
    assignment_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    The caller's own submission, or null if they have not submitted.

    Returns 200 with a null body rather than 404: "no submission yet" is the
    normal state and should not read as an error in the client.
    """
    authz.assert_course_member(course_id, current_user)
    authz.assert_assignment_in_course(assignment_id, course_id)
    return await classroom_service.get_student_submission(assignment_id, current_user.id)


@router.get("/submissions/{submission_id}/download", response_model=DownloadResponse)
async def download_submission(
    submission_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    A signed URL for a submitted file.

    Readable by the student who submitted it, a teacher of that course, or an
    admin — enforced by `authz.assert_submission_access`.
    """
    settings = get_settings()
    submission = authz.assert_submission_access(submission_id, current_user)

    if not submission.get("file_url"):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This submission has no attached file."
        )

    try:
        url = storage_service.create_signed_url(
            submission["file_url"],
            settings.BUCKET_SUBMISSIONS,
            download_name=submission.get("file_name"),
        )
    except storage_service.StorageError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The file could not be retrieved. {exc}"
        ) from exc

    return DownloadResponse(
        download_url=url,
        file_name=submission.get("file_name") or "submission",
        expires_in_seconds=settings.SIGNED_URL_TTL_SECONDS,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Grading
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/{course_id}/grades", response_model=GradeResponse, status_code=status.HTTP_201_CREATED
)
async def grade_submission(
    course_id: str,
    data: GradeCreate,
    current_user: CurrentUser = Depends(require_role("admin", "teacher")),
):
    """
    Award points and optional written feedback (PRD §9, "Grading").

    The score is validated against the assignment's `max_points`, and the
    resulting notice is addressed to that student alone — a grade must not
    appear on the whole course's Notice Board.
    """
    authz.assert_course_staff(course_id, current_user)
    submission = authz.assert_submission_access(data.submission_id, current_user)

    assignment = submission.get("assignments") or {}
    if assignment.get("course_id") != course_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")

    max_points = assignment.get("max_points") or 100
    if data.points_awarded > max_points:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{data.points_awarded} exceeds this assignment's maximum of {max_points}.",
        )

    grade = await classroom_service.grade_submission(
        submission_id=data.submission_id,
        graded_by=current_user.id,
        points_awarded=data.points_awarded,
        feedback_text=data.feedback_text,
    )

    feedback = f" Feedback: {data.feedback_text}" if data.feedback_text else ""
    await notice_service.create_system_notice(
        title=f"Grade posted: {assignment.get('title', 'Assignment')}",
        body=f"You scored {data.points_awarded} out of {max_points}.{feedback}",
        notice_type="grade",
        course_id=course_id,
        posted_by=current_user.id,
        target_user_id=submission["student_id"],
    )

    return grade
