-- ============================================================================
-- Academix AI — Authoritative database schema
--
-- This is the single source of truth for the database. It is fully idempotent
-- and safe to run against either a brand-new Supabase project or the existing
-- pilot database, which was built from an earlier draft and is missing every
-- Classroom table and names the RAG tables `rag_*`.
--
-- Apply with:   cd backend && python -m scripts.migrate
-- Or paste into Supabase Dashboard -> SQL Editor and run.
--
-- Shape follows the PRD data model: §8.3 (RAG core), §9.1 (Classroom),
-- §10 (Scheduler), §11 (Notice Board).
--
-- SECURITY POSTURE
--   The backend reaches Postgres exclusively with the service_role key and
--   enforces authorization in Python (app/services/authz.py). The browser uses
--   the anon key for Supabase Auth only — it never queries tables. So RLS is
--   enabled on every table with NO permissive policy, and the blanket
--   anon/authenticated grants are revoked: a deny-by-default posture. Do not
--   add permissive policies unless the frontend starts querying Postgres
--   directly.
-- ============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. Identity — profiles (mirrors auth.users)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.profiles (
    id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email      TEXT NOT NULL,
    full_name  TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('admin', 'teacher', 'student')),
    department TEXT,
    phone      TEXT,
    avatar_url TEXT,
    created_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
    updated_at TIMESTAMPTZ DEFAULT timezone('utc', now())
);

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS phone      TEXT,
    ADD COLUMN IF NOT EXISTS avatar_url TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT timezone('utc', now());

-- ============================================================================
-- 2. Courses, sections, enrollments
--
--    Department is a plain text attribute on the course (PRD §8.3
--    `Course(id, name, code, department, semester)`) rather than its own table
--    — this is a single-institute deployment (§3.3 non-goals) and the admin UI
--    picks from the distinct values already in use.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.courses (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    code            TEXT NOT NULL UNIQUE,
    description     TEXT,
    department_name TEXT,
    semester        INTEGER,
    banner_color    TEXT NOT NULL DEFAULT '#4285F4',
    created_by      UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT timezone('utc', now()),
    updated_at      TIMESTAMPTZ DEFAULT timezone('utc', now())
);

ALTER TABLE public.courses
    ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT timezone('utc', now());

CREATE TABLE IF NOT EXISTS public.sections (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id  UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
    UNIQUE (course_id, name)
);

CREATE TABLE IF NOT EXISTS public.enrollments (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    course_id   UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    section_id  UUID REFERENCES public.sections(id) ON DELETE SET NULL,
    role        TEXT NOT NULL CHECK (role IN ('teacher', 'student')),
    enrolled_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
    UNIQUE (user_id, course_id)
);

ALTER TABLE public.enrollments
    ADD COLUMN IF NOT EXISTS section_id UUID REFERENCES public.sections(id) ON DELETE SET NULL;

-- ============================================================================
-- 3. Classroom  (PRD §9 — full Google Classroom parity)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.announcements (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id       UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    posted_by       UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    text            TEXT NOT NULL,
    attachment_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    posted_at       TIMESTAMPTZ DEFAULT timezone('utc', now())
);

CREATE TABLE IF NOT EXISTS public.materials (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id   UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    uploaded_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    file_url    TEXT NOT NULL,
    file_name   TEXT NOT NULL,
    file_size   BIGINT,
    topic_tag   TEXT,
    created_at  TIMESTAMPTZ DEFAULT timezone('utc', now())
);

CREATE TABLE IF NOT EXISTS public.assignments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id       UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    created_by      UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    instructions    TEXT,
    attachment_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    due_at          TIMESTAMPTZ,
    max_points      INTEGER NOT NULL DEFAULT 100 CHECK (max_points > 0),
    topic_tag       TEXT,
    created_at      TIMESTAMPTZ DEFAULT timezone('utc', now()),
    updated_at      TIMESTAMPTZ DEFAULT timezone('utc', now())
);

CREATE TABLE IF NOT EXISTS public.submissions (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    assignment_id UUID NOT NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
    student_id    UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    file_url      TEXT,
    file_name     TEXT,
    text_response TEXT,
    submitted_at  TIMESTAMPTZ DEFAULT timezone('utc', now()),
    status        TEXT NOT NULL DEFAULT 'submitted'
                  CHECK (status IN ('not_submitted', 'submitted', 'late', 'graded')),
    UNIQUE (assignment_id, student_id)
);

CREATE TABLE IF NOT EXISTS public.grades (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_id  UUID NOT NULL UNIQUE REFERENCES public.submissions(id) ON DELETE CASCADE,
    points_awarded NUMERIC(8, 2) NOT NULL CHECK (points_awarded >= 0),
    feedback_text  TEXT,
    graded_by      UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    graded_at      TIMESTAMPTZ DEFAULT timezone('utc', now())
);

-- ============================================================================
-- 4. RAG corpus  (PRD §8.2 Stage 1 — ingestion & indexing)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.content_documents (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id     UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    uploaded_by   UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    material_id   UUID REFERENCES public.materials(id) ON DELETE CASCADE,
    file_url      TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    file_size     BIGINT,
    source_type   TEXT NOT NULL CHECK (source_type IN ('notes', 'textbook', 'pyq')),
    exam_type     TEXT CHECK (exam_type IN ('internal', 'external')),
    year          INTEGER,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'indexed', 'failed')),
    error_message TEXT,
    page_count    INTEGER,
    chunk_count   INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT timezone('utc', now()),
    updated_at    TIMESTAMPTZ DEFAULT timezone('utc', now())
);

-- Lets the Classwork list show live ingestion status next to each material.
ALTER TABLE public.materials
    ADD COLUMN IF NOT EXISTS document_id UUID
        REFERENCES public.content_documents(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.content_chunks (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES public.content_documents(id) ON DELETE CASCADE,
    course_id   UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    topic_tag   TEXT,
    page_ref    TEXT,
    source_type TEXT NOT NULL,
    exam_type   TEXT,
    chunk_index INTEGER NOT NULL,
    token_count INTEGER,
    embedding   vector(384),
    created_at  TIMESTAMPTZ DEFAULT timezone('utc', now())
);

-- ============================================================================
-- 5. Exam-style learning  (PRD §8.2 Stage 2 — style profiles from PYQs)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.pyq_questions (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id   UUID NOT NULL REFERENCES public.content_documents(id) ON DELETE CASCADE,
    course_id     UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    marks         INTEGER,
    section       TEXT,
    question_type TEXT,
    bloom_level   TEXT CHECK (bloom_level IN
                  ('remember', 'understand', 'apply', 'analyze', 'evaluate', 'create')),
    topic_tag     TEXT,
    year          INTEGER,
    exam_type     TEXT CHECK (exam_type IN ('internal', 'external')),
    created_at    TIMESTAMPTZ DEFAULT timezone('utc', now())
);

CREATE TABLE IF NOT EXISTS public.style_profiles (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    course_id          UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    exam_type          TEXT NOT NULL CHECK (exam_type IN ('internal', 'external')),
    total_marks        INTEGER,
    duration_minutes   INTEGER,
    section_structure  JSONB NOT NULL DEFAULT '[]'::jsonb,
    bloom_distribution JSONB NOT NULL DEFAULT '{}'::jsonb,
    common_patterns    JSONB NOT NULL DEFAULT '{}'::jsonb,
    question_count     INTEGER NOT NULL DEFAULT 0,
    confidence_score   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    pyq_count          INTEGER NOT NULL DEFAULT 0,
    last_computed_at   TIMESTAMPTZ DEFAULT timezone('utc', now()),
    UNIQUE (course_id, exam_type)
);

-- ============================================================================
-- 6. RAG output  (PRD §8.3 — generated sets, questions, attempts)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.generated_sets (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    requested_by      UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    course_id         UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    mode              TEXT NOT NULL CHECK (mode IN ('quiz_generation', 'paper_style')),
    exam_type         TEXT CHECK (exam_type IN ('internal', 'external')),
    topic_tags        JSONB NOT NULL DEFAULT '[]'::jsonb,
    difficulty        TEXT NOT NULL DEFAULT 'medium'
                      CHECK (difficulty IN ('easy', 'medium', 'hard')),
    status            TEXT NOT NULL DEFAULT 'generating'
                      CHECK (status IN ('generating', 'draft', 'approved', 'rejected', 'failed')),
    total_marks       INTEGER,
    total_questions   INTEGER,
    generation_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message     TEXT,
    approved_at       TIMESTAMPTZ,
    approved_by       UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ DEFAULT timezone('utc', now()),
    updated_at        TIMESTAMPTZ DEFAULT timezone('utc', now())
);

CREATE TABLE IF NOT EXISTS public.generated_questions (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    set_id             UUID NOT NULL REFERENCES public.generated_sets(id) ON DELETE CASCADE,
    question_text      TEXT NOT NULL,
    question_type      TEXT NOT NULL CHECK (question_type IN
                       ('mcq', 'short_answer', 'long_answer', 'true_false', 'fill_blank')),
    options            JSONB,
    correct_answer     TEXT NOT NULL,
    explanation        TEXT,
    marks              INTEGER NOT NULL DEFAULT 1 CHECK (marks > 0),
    bloom_level        TEXT CHECK (bloom_level IN
                       ('remember', 'understand', 'apply', 'analyze', 'evaluate', 'create')),
    section            TEXT,
    source_chunk_ids   JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_texts       JSONB NOT NULL DEFAULT '[]'::jsonb,
    faithfulness_score DOUBLE PRECISION,
    verification_note  TEXT,
    teacher_edited     BOOLEAN NOT NULL DEFAULT FALSE,
    question_order     INTEGER NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ DEFAULT timezone('utc', now())
);

CREATE TABLE IF NOT EXISTS public.student_quiz_attempts (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_id         UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    set_id             UUID NOT NULL REFERENCES public.generated_sets(id) ON DELETE CASCADE,
    answers            JSONB NOT NULL DEFAULT '{}'::jsonb,
    score              DOUBLE PRECISION,
    total_marks        INTEGER,
    auto_graded_marks  INTEGER,
    started_at         TIMESTAMPTZ DEFAULT timezone('utc', now()),
    submitted_at       TIMESTAMPTZ,
    time_spent_seconds INTEGER,
    status             TEXT NOT NULL DEFAULT 'in_progress'
                       CHECK (status IN ('in_progress', 'submitted'))
);

-- ============================================================================
-- 7. Scheduler  (PRD §10 — native calendar)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.calendar_events (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title            TEXT NOT NULL,
    description      TEXT,
    event_type       TEXT NOT NULL,
    start_at         TIMESTAMPTZ NOT NULL,
    end_at           TIMESTAMPTZ NOT NULL,
    course_id        UUID REFERENCES public.courses(id) ON DELETE CASCADE,
    section_id       UUID REFERENCES public.sections(id) ON DELETE SET NULL,
    assignment_id    UUID REFERENCES public.assignments(id) ON DELETE CASCADE,
    invitee_id       UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    semester         TEXT,
    location         TEXT,
    creator_id       UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    color            TEXT NOT NULL DEFAULT '#4285F4',
    is_all_day       BOOLEAN NOT NULL DEFAULT FALSE,
    reminder_minutes INTEGER NOT NULL DEFAULT 30,
    created_at       TIMESTAMPTZ DEFAULT timezone('utc', now()),
    updated_at       TIMESTAMPTZ DEFAULT timezone('utc', now())
);

ALTER TABLE public.calendar_events
    ADD COLUMN IF NOT EXISTS section_id       UUID REFERENCES public.sections(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS assignment_id    UUID REFERENCES public.assignments(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS invitee_id       UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS semester         TEXT,
    ADD COLUMN IF NOT EXISTS is_all_day       BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS reminder_minutes INTEGER NOT NULL DEFAULT 30,
    ADD COLUMN IF NOT EXISTS updated_at       TIMESTAMPTZ DEFAULT timezone('utc', now());

-- Recreate rather than ADD IF NOT EXISTS: the earlier draft shipped a narrower
-- event_type list that rejects 'assignment_due' and 'holiday'.
ALTER TABLE public.calendar_events DROP CONSTRAINT IF EXISTS calendar_events_event_type_check;
ALTER TABLE public.calendar_events
    ADD CONSTRAINT calendar_events_event_type_check
    CHECK (event_type IN ('lecture', 'meeting', 'exam', 'assignment_due', 'holiday', 'other'));

ALTER TABLE public.calendar_events DROP CONSTRAINT IF EXISTS calendar_events_valid_time_range;
ALTER TABLE public.calendar_events
    ADD CONSTRAINT calendar_events_valid_time_range CHECK (end_at > start_at);

-- One auto-generated due-date event per assignment, so editing an assignment
-- updates its calendar entry instead of duplicating it.
CREATE UNIQUE INDEX IF NOT EXISTS uq_calendar_events_assignment
    ON public.calendar_events (assignment_id) WHERE assignment_id IS NOT NULL;

-- ============================================================================
-- 8. Notice Board  (PRD §11)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.notices (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title          TEXT NOT NULL,
    body           TEXT NOT NULL,
    notice_type    TEXT NOT NULL DEFAULT 'announcement',
    course_id      UUID REFERENCES public.courses(id) ON DELETE CASCADE,
    author_id      UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    -- Institute-wide notices can be narrowed to particular roles…
    target_roles   JSONB NOT NULL DEFAULT '["admin", "teacher", "student"]'::jsonb,
    -- …and personal ones (a grade posted, say) to a single recipient.
    target_user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    created_at     TIMESTAMPTZ DEFAULT timezone('utc', now())
);

ALTER TABLE public.notices
    ADD COLUMN IF NOT EXISTS target_roles JSONB NOT NULL
        DEFAULT '["admin", "teacher", "student"]'::jsonb,
    ADD COLUMN IF NOT EXISTS target_user_id UUID
        REFERENCES public.profiles(id) ON DELETE CASCADE;

ALTER TABLE public.notices DROP CONSTRAINT IF EXISTS notices_notice_type_check;
ALTER TABLE public.notices
    ADD CONSTRAINT notices_notice_type_check CHECK (notice_type IN
    ('announcement', 'assignment', 'grade', 'event', 'material', 'system', 'admin'));

CREATE TABLE IF NOT EXISTS public.notice_reads (
    id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    notice_id UUID NOT NULL REFERENCES public.notices(id) ON DELETE CASCADE,
    user_id   UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    read_at   TIMESTAMPTZ DEFAULT timezone('utc', now()),
    UNIQUE (notice_id, user_id)
);

-- ============================================================================
-- 9. Retire superseded legacy tables
--
--    The pilot DB carries `rag_documents / rag_chunks / rag_sets /
--    rag_questions / quiz_attempts` from an earlier draft. They are replaced by
--    the PRD-named tables above. Dropped only when verified empty, so a
--    database that somehow accumulated rows is left alone and reported instead.
-- ============================================================================

DO $$
DECLARE
    legacy TEXT;
    n      BIGINT;
BEGIN
    FOREACH legacy IN ARRAY ARRAY[
        'rag_questions', 'rag_sets', 'rag_chunks', 'rag_documents', 'quiz_attempts'
    ]
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = legacy
        ) THEN
            EXECUTE format('SELECT count(*) FROM public.%I', legacy) INTO n;
            IF n = 0 THEN
                EXECUTE format('DROP TABLE public.%I CASCADE', legacy);
                RAISE NOTICE 'Dropped empty legacy table "%"', legacy;
            ELSE
                RAISE WARNING 'KEPT legacy table "%" — it holds % row(s). Migrate the data, then drop it manually.', legacy, n;
            END IF;
        END IF;
    END LOOP;
END $$;

-- ============================================================================
-- 10. Indexes
-- ============================================================================

-- Semantic half of retrieval (HNSW, cosine distance).
CREATE INDEX IF NOT EXISTS idx_content_chunks_embedding
    ON public.content_chunks USING hnsw (embedding vector_cosine_ops);

-- Keyword half of the hybrid retrieval in PRD §8.2 Stage 3.
CREATE INDEX IF NOT EXISTS idx_content_chunks_text_fts
    ON public.content_chunks USING gin (to_tsvector('english', text));

CREATE INDEX IF NOT EXISTS idx_sections_course          ON public.sections (course_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_user         ON public.enrollments (user_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_course       ON public.enrollments (course_id);
CREATE INDEX IF NOT EXISTS idx_announcements_course     ON public.announcements (course_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_materials_course         ON public.materials (course_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_materials_document       ON public.materials (document_id);
CREATE INDEX IF NOT EXISTS idx_assignments_course       ON public.assignments (course_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assignments_due          ON public.assignments (due_at);
CREATE INDEX IF NOT EXISTS idx_submissions_assignment   ON public.submissions (assignment_id);
CREATE INDEX IF NOT EXISTS idx_submissions_student      ON public.submissions (student_id);
CREATE INDEX IF NOT EXISTS idx_grades_submission        ON public.grades (submission_id);
CREATE INDEX IF NOT EXISTS idx_content_documents_course ON public.content_documents (course_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_documents_status ON public.content_documents (status);
CREATE INDEX IF NOT EXISTS idx_content_chunks_course    ON public.content_chunks (course_id);
CREATE INDEX IF NOT EXISTS idx_content_chunks_document  ON public.content_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_pyq_questions_course     ON public.pyq_questions (course_id, exam_type);
CREATE INDEX IF NOT EXISTS idx_pyq_questions_document   ON public.pyq_questions (document_id);
CREATE INDEX IF NOT EXISTS idx_generated_sets_user      ON public.generated_sets (requested_by, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generated_sets_course    ON public.generated_sets (course_id);
CREATE INDEX IF NOT EXISTS idx_generated_questions_set  ON public.generated_questions (set_id, question_order);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_student    ON public.student_quiz_attempts (student_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_set        ON public.student_quiz_attempts (set_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_dates    ON public.calendar_events (start_at, end_at);
CREATE INDEX IF NOT EXISTS idx_calendar_events_course   ON public.calendar_events (course_id);
CREATE INDEX IF NOT EXISTS idx_notices_created          ON public.notices (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notices_course           ON public.notices (course_id);
CREATE INDEX IF NOT EXISTS idx_notices_target_user      ON public.notices (target_user_id);
CREATE INDEX IF NOT EXISTS idx_notice_reads_user        ON public.notice_reads (user_id);

-- ============================================================================
-- 11. Hybrid retrieval RPC  (PRD §8.2 Stage 3)
--
--     Replaces the earlier `match_chunks(query_embedding, filter_course_id,
--     match_threshold, match_count)`, which read the now-dropped `rag_chunks`
--     and supported no metadata filtering.
--
--     Score = (1 - w)·cosine_similarity + w·normalised_keyword_rank, so a chunk
--     that is both semantically close AND literally mentions the topic outranks
--     one that only does the former. Metadata (course / source_type /
--     exam_type / topic) is applied as HARD filters per PRD §15 — the mitigation
--     for "retrieval pulls an irrelevant chunk" is explicitly *not* pure
--     semantic search.
-- ============================================================================

DROP FUNCTION IF EXISTS public.match_chunks(vector, uuid, double precision, integer);
DROP FUNCTION IF EXISTS public.match_chunks(vector, uuid, text, text, text, double precision, integer);
DROP FUNCTION IF EXISTS public.match_chunks(vector, uuid, text, text, text, text, double precision, integer, double precision);

CREATE FUNCTION public.match_chunks(
    query_embedding  vector(384),
    p_course_id      UUID,
    p_source_type    TEXT             DEFAULT NULL,
    p_exam_type      TEXT             DEFAULT NULL,
    p_topic_tag      TEXT             DEFAULT NULL,
    p_query_text     TEXT             DEFAULT NULL,
    match_threshold  DOUBLE PRECISION DEFAULT 0.25,
    match_count      INTEGER          DEFAULT 10,
    keyword_weight   DOUBLE PRECISION DEFAULT 0.25
)
RETURNS TABLE (
    id           UUID,
    document_id  UUID,
    text         TEXT,
    topic_tag    TEXT,
    page_ref     TEXT,
    source_type  TEXT,
    exam_type    TEXT,
    chunk_index  INTEGER,
    similarity   DOUBLE PRECISION,
    keyword_rank DOUBLE PRECISION,
    hybrid_score DOUBLE PRECISION
)
LANGUAGE sql
STABLE
AS $fn$
    WITH q AS (
        SELECT CASE
                   WHEN p_query_text IS NULL OR btrim(p_query_text) = '' THEN NULL
                   ELSE websearch_to_tsquery('english', p_query_text)
               END AS tsq
    ),
    scored AS (
        SELECT
            cc.id,
            cc.document_id,
            cc.text,
            cc.topic_tag,
            cc.page_ref,
            cc.source_type,
            cc.exam_type,
            cc.chunk_index,
            (1 - (cc.embedding <=> query_embedding))::DOUBLE PRECISION AS similarity,
            COALESCE(
                CASE WHEN q.tsq IS NULL THEN 0
                     ELSE ts_rank_cd(to_tsvector('english', cc.text), q.tsq)
                END, 0
            )::DOUBLE PRECISION AS keyword_rank
        FROM public.content_chunks cc
        CROSS JOIN q
        WHERE cc.course_id = p_course_id
          AND cc.embedding IS NOT NULL
          AND (p_source_type IS NULL OR cc.source_type = p_source_type)
          AND (p_exam_type   IS NULL OR cc.exam_type   = p_exam_type)
          AND (p_topic_tag   IS NULL OR cc.topic_tag   = p_topic_tag)
    ),
    normalised AS (
        SELECT
            s.*,
            -- ts_rank_cd is unbounded, so scale it against the best hit in this
            -- candidate set to make the two signals comparable.
            CASE WHEN MAX(s.keyword_rank) OVER () > 0
                 THEN s.keyword_rank / MAX(s.keyword_rank) OVER ()
                 ELSE 0
            END AS keyword_norm
        FROM scored s
    )
    SELECT
        n.id,
        n.document_id,
        n.text,
        n.topic_tag,
        n.page_ref,
        n.source_type,
        n.exam_type,
        n.chunk_index,
        n.similarity,
        n.keyword_rank,
        ((1 - keyword_weight) * n.similarity + keyword_weight * n.keyword_norm)
            ::DOUBLE PRECISION AS hybrid_score
    FROM normalised n
    -- Keep a chunk if EITHER signal likes it: semantic hits above the threshold,
    -- plus strong literal keyword matches the embedding happened to miss.
    WHERE n.similarity >= match_threshold OR n.keyword_norm >= 0.5
    ORDER BY hybrid_score DESC
    LIMIT match_count;
$fn$;

-- ============================================================================
-- 12. Triggers
-- ============================================================================

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $fn$
BEGIN
    NEW.updated_at = timezone('utc', now());
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'profiles', 'courses', 'assignments', 'calendar_events',
        'content_documents', 'generated_sets'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_set_updated_at ON public.%I', t);
        EXECUTE format(
            'CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()', t);
    END LOOP;
END $$;

-- Keep content_documents.chunk_count honest even if ingestion is interrupted or
-- chunks are deleted. Statement-level with transition tables, not per-row:
-- ingesting a 500-chunk document must not fire 500 recounts.
CREATE OR REPLACE FUNCTION public.sync_document_chunk_count()
RETURNS TRIGGER AS $fn$
BEGIN
    UPDATE public.content_documents d
       SET chunk_count = sub.n
      FROM (
        SELECT c.document_id, count(*) AS n
          FROM public.content_chunks c
         WHERE c.document_id IN (SELECT document_id FROM changed)
         GROUP BY c.document_id
      ) sub
     WHERE d.id = sub.document_id;

    -- Documents whose chunks were all removed drop out of the GROUP BY above.
    UPDATE public.content_documents d
       SET chunk_count = 0
     WHERE d.id IN (SELECT document_id FROM changed)
       AND NOT EXISTS (SELECT 1 FROM public.content_chunks c WHERE c.document_id = d.id);

    RETURN NULL;
END;
$fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_chunk_count_ins ON public.content_chunks;
CREATE TRIGGER trg_sync_chunk_count_ins
    AFTER INSERT ON public.content_chunks
    REFERENCING NEW TABLE AS changed
    FOR EACH STATEMENT EXECUTE FUNCTION public.sync_document_chunk_count();

DROP TRIGGER IF EXISTS trg_sync_chunk_count_del ON public.content_chunks;
CREATE TRIGGER trg_sync_chunk_count_del
    AFTER DELETE ON public.content_chunks
    REFERENCING OLD TABLE AS changed
    FOR EACH STATEMENT EXECUTE FUNCTION public.sync_document_chunk_count();

-- Mirror auth.users into profiles on signup.
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $fn$
BEGIN
    INSERT INTO public.profiles (id, email, full_name, role, department)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NULLIF(NEW.raw_user_meta_data ->> 'full_name', ''),
                 split_part(NEW.email, '@', 1)),
        COALESCE(NULLIF(NEW.raw_user_meta_data ->> 'role', ''), 'student'),
        NULLIF(NEW.raw_user_meta_data ->> 'department', '')
    )
    ON CONFLICT (id) DO UPDATE
        SET email     = EXCLUDED.email,
            full_name = COALESCE(EXCLUDED.full_name, public.profiles.full_name),
            role      = COALESCE(EXCLUDED.role, public.profiles.role);
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ============================================================================
-- 13. Row Level Security — deny by default (see SECURITY POSTURE header)
-- ============================================================================

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'profiles', 'courses', 'sections', 'enrollments',
        'announcements', 'materials', 'assignments', 'submissions', 'grades',
        'calendar_events', 'notices', 'notice_reads',
        'content_documents', 'content_chunks', 'pyq_questions', 'style_profiles',
        'generated_sets', 'generated_questions', 'student_quiz_attempts'
    ]
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = t
        ) THEN
            -- RLS on with no permissive policy = deny-by-default for anon and
            -- authenticated. (Deliberately NOT `FORCE ROW LEVEL SECURITY`: that
            -- only adds coverage for the table owner, which is unreachable
            -- through the API, and risks locking the backend out.)
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
            -- Belt and braces: drop the blanket grants PostgREST exposes, so a
            -- leaked anon or end-user JWT cannot read tables directly either.
            EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', t);
        END IF;
    END LOOP;
END $$;

-- service_role must retain full access: it is the backend's only identity.
GRANT USAGE ON SCHEMA public TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;

REVOKE ALL ON FUNCTION public.match_chunks(
    vector, uuid, text, text, text, text, double precision, integer, double precision
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.match_chunks(
    vector, uuid, text, text, text, text, double precision, integer, double precision
) TO service_role;

-- ============================================================================
-- 14. Storage buckets
--
--     Course content and submissions are PRIVATE; the backend issues
--     short-lived signed URLs (PRD §13 Security, §14 role-based isolation).
--     `course-materials` was public in the earlier draft — flipped here.
-- ============================================================================

INSERT INTO storage.buckets (id, name, public)
VALUES ('course-materials', 'course-materials', false),
       ('pyq-papers',       'pyq-papers',       false),
       ('submissions',      'submissions',      false),
       ('avatars',          'avatars',          true)
ON CONFLICT (id) DO UPDATE SET public = EXCLUDED.public;

COMMIT;
