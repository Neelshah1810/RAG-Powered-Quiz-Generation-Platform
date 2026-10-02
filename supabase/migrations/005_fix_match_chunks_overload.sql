-- 005_fix_match_chunks_overload.sql
--
-- The 001_schema.sql migration created match_chunks with 9 params.
-- The 002_student_materials.sql migration added a 10-param version (with
-- p_uploaded_by) but forgot to DROP the old 9-param signature first.
-- Postgres can't resolve overloaded calls from PostgREST, causing PGRST203.
--
-- Fix: drop ALL existing match_chunks signatures, then create exactly one
-- canonical 10-param version that handles both cases (p_uploaded_by = NULL
-- means "no filter").

DROP FUNCTION IF EXISTS public.match_chunks(
    vector, uuid, text, text, text, text, double precision, integer, double precision);

DROP FUNCTION IF EXISTS public.match_chunks(
    vector, uuid, text, text, text, text, double precision, integer, double precision, uuid);

-- Also catch any older signatures that may still exist
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

-- Grant execute to authenticated and anon roles
GRANT EXECUTE ON FUNCTION public.match_chunks(
    vector, uuid, text, text, text, text, double precision, integer, double precision, uuid
) TO authenticated, anon, service_role;
