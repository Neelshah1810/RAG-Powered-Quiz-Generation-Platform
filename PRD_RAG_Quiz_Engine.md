# Product Requirements Document (PRD)
## Academix AI — RAG-Powered Quiz Generation Platform (Single Institute)

| | |
|---|---|
| **Document Owner** | Neel Shah, Yashvi Patel — Master's Research Project |
| **Version** | 2.0 (Post Faculty Review) |
| **Date** | August 30, 2026 |
| **Status** | Draft for Review |
| **Classification** | Academic Research / Production-Track Prototype |

> **Change Log (v1 → v2):** Scope narrowed from multi-tenant/multi-role to a **single-institute deployment with exactly three roles** (Admin, Teacher, Student). Classroom module upgraded to full **Google Classroom parity** (materials + assignments + submissions). Navigation is now fixed per role, per faculty direction. "Mock quiz" / "paper draft" terminology retired in favor of **Quiz Generation** (Student) and **Paper Style** (Teacher) — same underlying RAG engine, simplified framing. A dedicated **UI/UX Design System** section has been added, modeled on Google Classroom, Google Calendar, Gemini, and NotebookLM.

---

## 1. Executive Summary

Academix AI is a **single-institute** academic platform (built for our own college) with three roles — **Admin, Teacher, Student** — centered on a **Retrieval-Augmented Generation (RAG) Quiz Generation Engine**. The engine is grounded in the institute's own lecture notes, textbook material, and historical previous-year question papers (PYQs), so:

- **Students** get a **Quiz Generation** tool that produces practice quizzes matching their actual syllabus and their institute's real exam style.
- **Teachers** get a **Paper Style** tool that produces exam-ready draft questions following the institute's own historical exam patterns (internal vs. external), always subject to teacher review before use.

Around this core engine sit three supporting modules, each mapped 1:1 to a nav item every user sees: a **Classroom** built to full feature-parity with Google Classroom (materials, assignments, submissions, grading), a **Scheduler** (native calendar), and a **Notice Board** (announcements + notifications).

The product's visual and interaction design deliberately mirrors the Google Workspace family the users already know — **Google Classroom** (course cards, stream/classwork/people layout), **Google Calendar** (month/week/day grid, color-coded events), and **Gemini / NotebookLM** (conversational quiz-generation interface with a visible, citable "sources" panel) — so the learning curve for both students and teachers is close to zero.

---

## 2. Problem Statement

Students preparing for internal and external exams need practice material that reflects **what was actually taught** and **how their specific institute has historically examined that content**. Generic AI chatbots fail here because they have no access to the institute's actual notes, textbook slides, or PYQ archive, and produce output that is generic, occasionally inconsistent with what was taught, or mismatched in difficulty/format from the real exam.

Teachers, meanwhile, spend real effort each semester drafting question papers that must conform to the institute's own conventions (marks-per-question, section structure, cognitive-level spread) — repetitive work that is currently un-automated in any grounded, trustworthy way. And today, quiz practice, class material distribution, scheduling, and announcements all live in disconnected tools (or don't exist at all) instead of one place.

---

## 3. Goals & Objectives

### 3.1 Product Goals
- **G1.** Generate quiz/exam questions that are demonstrably grounded in the institute's own content (notes + textbook + PYQs), minimizing hallucination and factual drift.
- **G2.** Learn and reproduce the institute's exam *style* (format, marks pattern, section structure, cognitive-level distribution) separately for Internal and External exams.
- **G3.** Give students a self-serve **Quiz Generation** experience tied to their actual enrolled courses.
- **G4.** Give teachers a fast **Paper Style** first-draft tool, with mandatory human review before anything is used in a real exam.
- **G5.** Provide a **Classroom** experience at full parity with Google Classroom (stream, materials, assignments, submissions, grading) so the platform is a genuine daily-use tool, not just a quiz generator.
- **G6.** Keep the whole experience inside one, familiar, Google-Workspace-style interface.

### 3.2 Success Metrics (KPIs)
| Metric | Target (Semester Pilot, single institute) |
|---|---|
| % of generated questions rated "syllabus-aligned" by teacher review | ≥ 85% |
| % of generated questions requiring **no** factual correction | ≥ 80% |
| Teacher time to produce a first draft question set via Paper Style | < 10 minutes |
| Student weekly active usage of Quiz Generation per enrolled course | ≥ 40% of enrolled students/week |
| Retrieval precision@5 (relevant chunk retrieved in top 5) | ≥ 0.8 on internal eval set |
| Assignment submission rate via Classroom (vs. paper/email) | ≥ 70% of assignments submitted in-app |
| Notice/notification delivery success rate | ≥ 99% |

### 3.3 Non-Goals (Out of Scope for v1)
- **Multiple institutes / multi-tenancy** — this is a single-college deployment. No institute-switching, no cross-college data model.
- Proctoring / anti-cheating during **live/timed real exams** (this is a drafting + practice tool, not an exam-conduction/invigilation platform).
- Real integration with actual Google Calendar / Google Classroom APIs — the UI is **inspired by** them; the backend/data is fully native, per earlier decision.
- Auto-generating a **final, submission-ready** exam paper with zero human review — Paper Style always requires teacher sign-off before use.
- Advanced grading (rubrics, plagiarism detection, weighted grade-book/GPA) — v1 Classroom supports simple point-based grading only (see §9).
- Video conferencing / live lecture delivery — Scheduler only *schedules* the lecture; it does not host it.
- Mobile native apps (v1 is responsive web only).

---

## 4. Roles

Exactly **three roles**, matching the single-institute scope:

| Role | Description | Primary Needs |
|---|---|---|
| **Admin** | Manages the college's instance of the platform | Onboard teachers/students, create departments/courses/sections, view usage, post institute-wide notices, oversee content |
| **Teacher** | Teaches one or more courses | Use Paper Style to generate exam drafts, run Classroom (post material + assignments, grade submissions), schedule classes via Scheduler, post notices |
| **Student** | Enrolled in one or more courses | Use Quiz Generation for self-practice, access Classroom material/assignments, view Scheduler, read Notice Board |

There is no Super Admin / multi-institute layer in this version — `institute_id` still exists in the data model for cleanliness and future-proofing, but the product runs as a single fixed instance for our college.

### 4.1 Representative User Stories
- *As a student*, I want to open Quiz Generation, pick a subject/topic, and get a quiz that feels like it could appear in my exam, with an instant answer key.
- *As a teacher*, I want to open Paper Style, select a course + exam type (Internal/External), and get a draft set of questions in our usual format, with the source material each question came from clearly shown.
- *As a teacher*, I want to post lecture slides and also create an assignment with a due date in Classroom, exactly like I would in Google Classroom.
- *As a student*, I want to see all my assignments and materials in one Classroom feed, submit my work, and see my grade once the teacher grades it.
- *As a teacher/admin*, I want to schedule a lecture in Scheduler and have it show up automatically on my students' calendars.
- *As an admin*, I want to onboard our teachers and students, set up our courses/sections, and post a college-wide notice.

---

## 5. Navigation — Fixed Per Role

This is a hard product requirement, not just a suggestion — each role sees exactly this left-hand navigation (mirroring the Google Classroom sidebar pattern):

**Teacher navigation:**
1. Dashboard
2. Paper Style *(core AI feature — exam/question generation)*
3. Classroom
4. Scheduler
5. Notice Board

**Student navigation:**
1. Dashboard
2. Quiz Generation *(core AI feature — self-practice)*
3. Classroom
4. Scheduler
5. Notice Board

**Admin navigation** *(not explicitly specified by faculty review — proposed for completeness, flagged in §20 for confirmation):*
1. Dashboard
2. Manage Users (Teachers/Students)
3. Manage Courses & Sections
4. Classroom *(oversight view)*
5. Scheduler *(institute-wide view)*
6. Notice Board

No other top-level nav items exist in v1 — everything else (settings, profile, logout) lives behind the top-right account menu, matching Google Workspace convention.

---

## 6. High-Level System Overview

Single-institute deployment, three roles, one shared auth/identity layer, five functional areas behind that fixed navigation.

```
                      ┌─────────────────────────────┐
                      │        React Frontend         │
                      │  Google-Workspace-style UI    │
                      │ (Admin / Teacher / Student     │
                      │  fixed sidebars per §5)        │
                      └───────────────┬───────────────┘
                                       │ REST/HTTPS (JWT)
                      ┌───────────────▼───────────────┐
                      │        FastAPI Backend         │
                      │  (modular monolith)            │
                      ├────────────────────────────────┤
                      │ Auth & RBAC │ Classroom │ Sched.│
                      │ Notice Board/Notifications      │
                      │ ── Quiz Generation / Paper Style │
                      │        (RAG Engine, core)        │
                      └──┬───────────┬───────────┬─────┘
                         │           │           │
                 ┌───────▼──┐  ┌─────▼─────┐ ┌───▼────────┐
                 │ Postgres │  │  Qdrant    │ │ Object     │
                 │ (relational│ │  Vector    │ │ Storage    │
                 │ data:     │  │  Database  │ │ (S3-compat,│
                 │ users,    │  │ (dedicated)│ │ raw files, │
                 │ courses,  │  │            │ │ submissions)│
                 │ calendar, │  │            │ │            │
                 │ classroom)│  │            │ │            │
                 └──────────┘  └────────────┘ └────────────┘
                         │
                 ┌───────▼────────┐      ┌────────────────┐
                 │ Celery + Redis │──────▶  Groq API        │
                 │ (async jobs:   │      │ (LLM inference:  │
                 │ ingestion,     │      │  generation,     │
                 │ generation,    │      │  classification) │
                 │ email/notice)  │      └────────────────┘
                 └────────────────┘
```

Modular monolith, single FastAPI codebase, module boundaries kept clean for future extraction if ever needed — but there is **no requirement to support more than one institute**, which meaningfully simplifies the data model and admin tooling versus v1.0 of this PRD.

---

## 7. Technology Stack & Justification

| Layer | Choice | Why |
|---|---|---|
| Backend framework | **FastAPI (Python)** | Async-native (important for LLM/IO-bound calls), automatic OpenAPI docs, Pydantic validation pairs naturally with structured LLM outputs. |
| Frontend | **React** (Vite) + TypeScript, TailwindCSS | Component reuse across 3 role-based dashboards; matches the card/sidebar-heavy Google Workspace look targeted in §10. |
| Primary database | **PostgreSQL** | Relational store for users, courses, enrollments, calendar events, classroom/assignment data, quiz metadata. |
| Vector store | **Qdrant** (dedicated, self-hostable vector database) | Purpose-built vector DB with strong metadata filtering (course/topic/exam_type alongside similarity search); open-source and self-hostable. |
| Object storage | **S3-compatible** (AWS S3 or self-hosted MinIO) | Stores raw notes/PYQ files and student assignment submissions independent of the DB. |
| Async task queue | **Celery + Redis** | Ingestion, quiz/paper generation, and email/notice delivery are all async jobs that must not block requests. |
| Auth | **JWT (access + refresh tokens)**, `bcrypt`/`argon2` password hashing | Standard, stateless, carries role claims for RBAC across exactly 3 roles. |
| LLM (generation) | **Groq API**, abstracted via an internal `LLMProvider` interface | Groq's low-latency inference suits the multi-pass pipeline in §8 (generation + Bloom's classification + faithfulness/answer-drift checks per question set); abstraction keeps the door open to benchmark other providers for the research write-up. |
| Embeddings | Abstracted via the same provider interface; default a strong open embedding model (e.g. `bge-large`/`e5-large`) | Kept independent of Groq (used for LLM inference, not embeddings); swappable for on-prem/privacy needs. |
| Email/Notice delivery | Transactional email provider (e.g. SendGrid/SES) via Celery worker | Backs the Notice Board's email-notification side. |

---

## 8. Core Feature — RAG Engine: Quiz Generation (Student) & Paper Style (Teacher)

This is the product's core and receives the most design detail. **One underlying RAG engine powers both nav items** — the difference is mode, review requirements, and corpus visibility, not two separate systems.

### 8.1 Inputs to the Engine
1. **Course Material** — lecture notes, slides, textbook excerpts uploaded by teachers via Classroom (PDF, DOCX, PPTX, TXT).
2. **Historical PYQ Corpus** — past question papers, tagged by course/subject, exam type (**Internal** vs **External**), year, and (where available) marks-per-question and section — uploaded by teachers/admin.
3. **Generation Request** — course, topic(s)/unit(s), exam type to emulate (Teacher only), difficulty, question count/format.

### 8.2 Pipeline

**Stage 1 — Ingestion & Indexing** (async, triggered automatically on any Classroom upload)
- Extract text from uploaded files (PDF/DOCX/PPTX parsers).
- Chunk content semantically (~300–500 tokens, with overlap).
- Generate embeddings per chunk; store in Qdrant with payload metadata: `course_id, topic tag, source_type (notes|textbook|pyq), exam_type, year, doc_id`.
- For PYQs specifically, extract structural metadata: question text, marks, section, question type, and an LLM-assisted Bloom's-taxonomy level — this is what lets the engine learn "exam style," not just content.

**Stage 2 — Style Profile Construction** (per course + exam type, Paper Style only)
Built from tagged historical PYQs: typical total marks/duration, section structure (e.g., "Section A: 5×2 marks MCQ..."), cognitive-level distribution, and recurring phrasing/command-word patterns. Recomputed as new PYQs are added.

**Stage 3 — Retrieval**
Hybrid retrieval (dense vector similarity in Qdrant + metadata filters, optionally boosted with keyword search) pulls (a) the most relevant **content chunks** for factual grounding, and, for Paper Style, (b) structurally similar **historical PYQ questions** as style exemplars (used as pattern reference only, never copied verbatim).

**Stage 4 — Generation**
The LLM (via Groq) is prompted with the retrieved content as the **only permitted factual source**, plus the Style Profile (Paper Style mode only), and an explicit output schema (question text, options if MCQ, correct answer, marks, source-chunk citations, cognitive level).
- **Quiz Generation (Student)**: instant, casual difficulty controls, answer key + explanation shown immediately, unlimited regeneration with varied questions.
- **Paper Style (Teacher)**: strict adherence to the course's Style Profile (marks totals must sum correctly, section structure must match), full source-citation per question, and an explicit **"Draft — Needs Review"** state until the teacher approves it.

**Stage 5 — Grounding & Quality Verification**
- **Faithfulness check**: a second pass verifies each question+answer is actually supported by its cited chunk(s); ungrounded items are discarded/regenerated, never surfaced.
- **Answer-drift check**: re-verifies the marked "correct" answer actually matches what the source material states.
- **Format validator** (Paper Style): confirms marks sum correctly, section counts match the Style Profile, and no near-duplicate questions appear in one set.

**Stage 6 — Human Review (Teacher only, Paper Style)**
Teacher reviews question-by-question, can edit/regenerate/delete individual items, and only then "Approves" the set. Approved sets are locked and versioned. **A generated set is never usable in a real exam until approved.**

**Stage 7 — Output**
- Student: interactive in-app quiz (auto-graded for objective types; self-assessed with a model answer for subjective ones).
- Teacher: structured in-app draft, exportable as PDF in v1.

### 8.3 Data Model (Core Entities)
```
Course(id, name, code, department, semester)
Enrollment(id, course_id, user_id, role[teacher|student], section)
ContentDocument(id, course_id, uploaded_by, file_url, source_type[notes|textbook|pyq], exam_type[internal|external|null], year, status)
ContentChunk(id, document_id, text, qdrant_point_id, topic_tag, page_ref)
PYQQuestion(id, document_id, question_text, marks, section, question_type, bloom_level, topic_tag)
StyleProfile(id, course_id, exam_type, total_marks, duration_min, section_structure[json], bloom_distribution[json], last_computed_at)
GeneratedSet(id, requested_by, course_id, mode[quiz_generation|paper_style], exam_type, status[draft|approved], total_marks)
GeneratedQuestion(id, set_id, text, type, options[json,nullable], correct_answer, marks, bloom_level, source_chunk_ids[array], faithfulness_score, teacher_edited[bool])
StudentQuizAttempt(id, student_id, set_id, answers[json], score, submitted_at)
```

---

## 9. Classroom — Full Google Classroom Parity

Per faculty direction, Classroom is not a stripped-down material repository — it replicates Google Classroom's core feature set:

| Google Classroom concept | Academix AI equivalent |
|---|---|
| **Stream** | Course home feed: announcements, new-material and new-assignment activity, in reverse-chronological order. |
| **Classwork tab — Materials** | Teacher uploads notes/slides/readings, organized into topics/units. Every upload auto-triggers RAG ingestion (§8.2 Stage 1), directly feeding both Quiz Generation and Paper Style. |
| **Classwork tab — Assignments** | Teacher creates an assignment: title, instructions, attachment(s), due date, point value. Appears to enrolled students immediately, with due-date reminders via Notice Board. |
| **Turn-in / Submission** | Student uploads a file (or types a text response) as their submission before/after the due date; late submissions are flagly marked. |
| **Grading** | Teacher opens a submissions list per assignment, assigns a point score (out of the assignment's max points) and optional written feedback per student. Simple point-based grading only — no rubric builder or weighted gradebook in v1 (§3.3). |
| **People tab** | Roster view: teacher(s) and enrolled students for the course, with basic contact/profile info. |
| **Class code / invite** | Admin/teacher enrolls students by roster assignment (bulk CSV via Admin) rather than a public join-code flow, since this is a single closed institute, not an open platform. |

### 9.1 Data Model Additions
```
Assignment(id, course_id, created_by, title, instructions, attachment_urls[array], due_at, max_points, topic_tag)
Submission(id, assignment_id, student_id, submitted_file_url|text_response, submitted_at, status[not_submitted|submitted|late|graded])
Grade(id, submission_id, points_awarded, feedback_text, graded_by, graded_at)
Announcement(id, course_id, posted_by, text, attachment_urls[array], posted_at)
```

---

## 10. Scheduler (Native Calendar)

- Teachers create events: **Lecture, Meeting, Exam, Assignment Due Date** (the latter auto-populated from Classroom assignments), scoped to a course/section, one-off or recurring, with reminder lead time.
- Students see a merged personal calendar across all enrolled courses.
- Conflict detection warns a teacher if a new event overlaps another one they've scheduled for the same section.
- Edits/cancellations trigger a Notice Board notification to affected students.
- Fully native (no external Google Calendar sync) — UI is modeled on Google Calendar's month/week/day grid with color-coded event types (see §12).

---

## 11. Notice Board (Announcements + Notifications)

A single place, per faculty direction, for institute/course-level communication — replacing a generic "notifications" concept with a concrete, visible feed:

| Trigger | Surface |
|---|---|
| New material or assignment posted | Course Notice Board + Classroom stream + email |
| Assignment due-date approaching (configurable lead time) | Notice Board + email |
| Scheduler event created/edited/cancelled | Notice Board + email |
| Assignment graded | Notice Board (student) |
| Paper Style set approved | Notice Board (teacher, audit confirmation) |
| Admin institute-wide notice | Notice Board (all users) + email |
| Account provisioned / password reset | Email |

All notices are queued via Celery for reliable delivery and retry-on-failure; the Notice Board screen itself shows an in-app, filterable feed (by course / by type).

---

## 12. UI/UX Design System — "Google Workspace" Direction

This is an explicit product requirement: the interface should feel immediately familiar to anyone who has used **Google Classroom, Google Calendar, Gemini, and NotebookLM** — not a generic admin-panel template.

### 12.1 Visual Language
- **Typography**: Google Sans / "Product Sans"-style geometric sans-serif for headings (fallback: `Inter` or `Roboto` for licensing-safe web use), Roboto for body text.
- **Color system**: a clean white/off-white canvas (`#FFFFFF` / `#F8F9FA`) with a single strong accent color per context — course cards each get an auto-assigned banner color/pattern from a fixed palette, exactly like Google Classroom's course tiles.
- **Shape language**: rounded corners (8–16px radius) on cards and buttons, soft single-level shadows (Material Design elevation, not heavy drop-shadows), generous whitespace.
- **Iconography**: Material Symbols icon set throughout (matches the Google product family exactly).

### 12.2 Layout Per Surface
- **Global shell**: persistent left sidebar with the fixed per-role nav from §5 (collapsible on smaller screens), a top app bar with search + account avatar (top-right), and a **floating "+" action button** for primary create actions (New Assignment, New Event, New Notice) — mirroring Classroom/Calendar conventions.
- **Classroom (Stream/Classwork/People)**: tabbed sub-navigation within a course exactly matching Classroom's own tab layout; course grid on the Classroom landing page shows color-banner cards per enrolled course.
- **Scheduler**: full month/week/day toggle calendar grid (Google Calendar layout), color-coded chips per event type (Lecture / Exam / Assignment Due / Meeting), click-to-expand event detail panel sliding in from the right (not a modal), matching Calendar's side-panel pattern.
- **Quiz Generation (Student) & Paper Style (Teacher)**: a **conversational, Gemini-style generation panel** — a clean centered input/prompt area ("What topic should today's quiz cover?") rather than a dense form, with generated questions streaming in below as they're produced. Alongside each generated question, a collapsible **"Sources" panel** in the style of **NotebookLM** — showing exactly which uploaded note/PYQ chunk each question was grounded in, so teachers/students can inspect provenance with one click, not dig through a settings page.
- **Notice Board**: a clean vertical feed of notice cards (icon + title + timestamp + course tag), filterable by course/type, similar to Classroom's Stream but scoped institute-wide when relevant.
- **Dashboard (per role)**: a lightweight home screen — for students: upcoming Scheduler events + pending assignments + a "Generate a quiz" quick-start card; for teachers: today's schedule + pending submissions to grade + a "Start Paper Style" quick-start card; for admin: institute-wide activity summary.

### 12.3 Interaction Principles
- Prefer **inline panels and slide-overs** over full-page navigation or modals wherever Google's own products do (event details, submission grading, source citations) — keeps the experience feeling like one continuous app, not a series of disconnected pages.
- Generation feedback should feel **live/conversational** (streaming text, subtle loading states) rather than a static "submit and wait" form, echoing the Gemini interaction model.
- Every AI-generated artifact (quiz question or paper-style question) must always be visually distinguishable from human-authored content (a small "AI-generated" tag), and must always expose its sources — this is a trust requirement, not just a style choice (ties back to §8.2 Stage 6 and §14).

---

## 13. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Performance** | Quiz Generation: p95 < 15s end-to-end. Paper Style (10–20 questions): p95 < 45s (async job with visible progress, not a blocking request). |
| **Scale** | Single-institute deployment: up to our full college's student/teacher population without architecture changes. |
| **Availability** | 99% uptime target for the pilot. |
| **Security** | HTTPS/TLS everywhere; passwords hashed (argon2/bcrypt); short-lived JWT access tokens + rotating refresh tokens; RBAC enforced server-side for all 3 roles; uploaded files type/virus-scanned before ingestion. |
| **Data Privacy** | Student PII (names, emails, grades, submissions) accessible only to that student, their teacher(s), and Admin. |
| **Auditability** | Every approved Paper Style set is versioned and immutable once locked, with a full source-citation trail per question. |
| **Accessibility** | WCAG 2.1 AA target for core flows (quiz-taking, assignment submission, Scheduler, Classroom). |

---

## 14. Security, Trust & Academic-Integrity Considerations

- **Students never see Paper Style outputs or the raw PYQ corpus** — students only ever interact with Quiz Generation, generated independently, so they cannot reverse-engineer an actual upcoming exam.
- **Draft-to-Approved gate is mandatory** (§8.2 Stage 6) — no generated question set can be used as a real exam until a teacher explicitly approves it.
- **Source-citation requirement** — every teacher-facing generated question shows which content chunk(s) it was grounded in, so a teacher can verify correctness in seconds.
- **Role-based data isolation** — a student can only ever see grades/submissions/content for courses they're enrolled in; a teacher can only see their own courses; only Admin has institute-wide visibility.

---

## 15. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Retrieval pulls an irrelevant chunk, producing an off-syllabus question | Hybrid retrieval with hard metadata filters (course/topic/exam_type) in Qdrant, not pure semantic search; visible source citations for manual catch |
| Generated "correct" answer subtly drifts from what source material actually says | Dedicated answer-drift verification pass (§8.2 Stage 5) before any question is surfaced |
| LLM hallucinates facts not present in retrieved content | Faithfulness-check pass; prompting that refuses generation when retrieval confidence is low |
| Style Profile inaccurate early on (too few PYQs uploaded) | Confidence indicator on Style Profiles below a data-volume threshold; generic formatting fallback until enough PYQs exist |
| Students attempting to access Paper Style / raw PYQ corpus to leak exam questions | Hard role-based separation of modes + corpus access (§14) |
| Assignment submissions lost/corrupted | Submissions stored in S3-compatible object storage with the same reliability guarantees as course material |

---

## 16. Phased Roadmap

**Phase 1 — Core MVP (this semester)**
- Auth/RBAC for 3 roles; Admin-provisioned Course/Section/Enrollment setup for our single college
- Content upload + ingestion pipeline (notes + PYQs) via Classroom
- Quiz Generation (Student) — MCQ + short-answer, instant answer key
- Basic Style Profile extraction from PYQs (Internal exam type first)
- Paper Style (Teacher) with mandatory review/approve flow
- Classroom: Stream, Materials, Assignments, Submissions, simple point grading, People tab
- Scheduler: create/view events, auto-populated assignment due dates
- Notice Board: in-app feed + email for core triggers
- UI shell per §12 (sidebar nav, course cards, calendar grid, conversational generation panel with sources)

**Phase 2 — Depth & Trust**
- External exam-type support with its own Style Profile
- Faithfulness + answer-drift verification fully productionized with logged confidence scores
- Teacher analytics: which topics students struggle with most (from Quiz Generation attempt data) — feeds back into teaching
- DOCX export of approved Paper Style sets matching a teacher-uploaded institute template

**Phase 3 — Polish**
- Richer grading (optional rubric support) while staying single-institute
- Export Scheduler to `.ics` for personal calendar apps (still no live Google Calendar sync, per scope)

---

## 17. Assumptions & Dependencies
- This is a single fixed college deployment — no institute-switching or onboarding of other institutes is required.
- The college can supply a seed corpus of digitized notes and at least 2–3 years of PYQs per course for Style Profile and retrieval quality to be meaningful.
- A Groq API budget/key and a Qdrant instance (self-hosted or managed) are available for the pilot.
- College email access is available for Notice Board email delivery.

## 18. Open Questions (for you to confirm)
1. Admin navigation (§5) was proposed, not specified in the faculty review — please confirm or adjust the exact Admin screen list.
2. Should grading in Classroom support partial-credit/rubrics in Phase 1, or is a single point score per assignment sufficient (current assumption: single point score, §9)?
3. Will the pilot corpus (notes + PYQs) come from your own courses this semester, or from department archives?

## 19. Glossary
- **RAG** — Retrieval-Augmented Generation: generating text using an LLM grounded in retrieved external content.
- **PYQ** — Previous Year Question (paper).
- **Style Profile** — the engine's learned representation of the institute's exam format/pattern for a course + exam type.
- **Faithfulness check** — automated verification that a generated question/answer is actually supported by its cited source content.
- **Bloom's Taxonomy level** — classification of a question's cognitive demand (Remember, Understand, Apply, Analyze, Evaluate, Create).
