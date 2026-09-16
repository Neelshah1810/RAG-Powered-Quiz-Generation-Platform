-- 002_student_materials.sql – adds support for student‑personal material uploads

-- 1. Allow the new source_type value
ALTER TABLE public.content_documents
  DROP CONSTRAINT IF EXISTS content_documents_source_type_check;
ALTER TABLE public.content_documents
  ADD CONSTRAINT content_documents_source_type_check
  CHECK (source_type IN ('notes', 'textbook', 'pyq', 'student_personal'));

-- 2. Track which user uploaded a chunk (for private material)
ALTER TABLE public.content_chunks
  ADD COLUMN IF NOT EXISTS uploaded_by UUID
    REFERENCES public.profiles(id) ON DELETE CASCADE;

-- 3. Index for fast per‑student lookups (only where uploaded_by is set)
CREATE INDEX IF NOT EXISTS idx_content_chunks_uploaded_by
  ON public.content_chunks (uploaded_by)
  WHERE uploaded_by IS NOT NULL;

-- 4. Extend match_chunks function to filter on uploaded_by
DROP FUNCTION IF EXISTS public.match_chunks(
    vector, uuid, text, text, text, text, double precision, integer, double precision, uuid);

CREATE FUNCTION public.match_chunks(
    query_embedding  vector(384),
    p_course_id      UUID,
    p_source_type    TEXT             DEFAULT NULL,
    p_exam_type      TEXT             DEFAULT NULL,
    p_topic_tag      TEXT             DEFAULT NULL,
    p_query_text     TEXT             DEFAULT NULL,
    match_threshold  DOUBLE PRECISION DEFAULT 0.25,
    match_count      INTEGER          DEFAULT 10,
    keyword_weight   DOUBLE PRECISION DEFAULT 0.25,
    p_uploaded_by    UUID             DEFAULT NULL
) RETURNS TABLE (
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
) LANGUAGE sql STABLE AS $fn$
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
          AND (p_uploaded_by IS NULL OR cc.uploaded_by = p_uploaded_by)
    ),
    normalised AS (
        SELECT s.*,
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
        ((1 - keyword_weight) * n.similarity + keyword_weight * n.keyword_norm)::DOUBLE PRECISION AS hybrid_score
    FROM normalised n
    WHERE n.similarity >= match_threshold OR n.keyword_norm >= 0.5
    ORDER BY hybrid_score DESC
    LIMIT match_count;
$fn$;
