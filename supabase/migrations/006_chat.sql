-- ============================================================================
-- 006_chat.sql — Teams/WhatsApp-style group chat
--
-- Groups are created by teachers/admins. Each group has a posting policy:
--   'admins'   — only group admins (teachers/admins) may send; students read,
--                react and vote in polls (announcement channel)
--   'everyone' — every member may send
--
-- Same security posture as 001_schema.sql: the backend is the only client
-- (service_role) and enforces membership in Python; RLS is on with no
-- permissive policy, so anon/authenticated JWTs cannot read these tables.
-- Idempotent: safe to re-run.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.chat_groups (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    description     TEXT,
    course_id       UUID REFERENCES public.courses(id) ON DELETE SET NULL,
    created_by      UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    post_policy     TEXT NOT NULL DEFAULT 'admins'
                    CHECK (post_policy IN ('admins', 'everyone')),
    color           TEXT NOT NULL DEFAULT '#4285F4',
    last_message_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
    created_at      TIMESTAMPTZ DEFAULT timezone('utc', now()),
    updated_at      TIMESTAMPTZ DEFAULT timezone('utc', now())
);

CREATE TABLE IF NOT EXISTS public.chat_members (
    group_id     UUID NOT NULL REFERENCES public.chat_groups(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    role         TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    added_by     UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    joined_at    TIMESTAMPTZ DEFAULT timezone('utc', now()),
    last_read_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
    PRIMARY KEY (group_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_chat_members_user ON public.chat_members (user_id);

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id     UUID NOT NULL REFERENCES public.chat_groups(id) ON DELETE CASCADE,
    sender_id    UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    kind         TEXT NOT NULL DEFAULT 'text' CHECK (kind IN ('text', 'poll', 'system')),
    body         TEXT,
    -- [{path, name, size, mime}] — path is "<bucket>/<group_id>/<key>"
    attachments  JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_important BOOLEAN NOT NULL DEFAULT FALSE,
    -- {question, options: [{id, text}], allow_multiple, closed}
    poll         JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    deleted_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_group_time
    ON public.chat_messages (group_id, created_at DESC);

-- One reaction per user per message (WhatsApp-style; re-reacting replaces).
CREATE TABLE IF NOT EXISTS public.chat_reactions (
    message_id UUID NOT NULL REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    emoji      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
    PRIMARY KEY (message_id, user_id)
);

CREATE TABLE IF NOT EXISTS public.chat_poll_votes (
    message_id UUID NOT NULL REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    option_id  TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
    PRIMARY KEY (message_id, user_id, option_id)
);

-- Per-group unread count + latest message for one user, in a single round-trip.
CREATE OR REPLACE FUNCTION public.chat_group_summaries(p_user_id UUID)
RETURNS TABLE (group_id UUID, unread_count INTEGER, last_message_id UUID, member_count INTEGER)
LANGUAGE sql STABLE AS $fn$
    SELECT
        m.group_id,
        (SELECT COUNT(*)::INTEGER FROM public.chat_messages cm
          WHERE cm.group_id = m.group_id
            AND cm.created_at > COALESCE(m.last_read_at, m.joined_at)
            AND cm.deleted_at IS NULL
            AND cm.sender_id IS DISTINCT FROM p_user_id) AS unread_count,
        (SELECT cm.id FROM public.chat_messages cm
          WHERE cm.group_id = m.group_id
          ORDER BY cm.created_at DESC LIMIT 1) AS last_message_id,
        (SELECT COUNT(*)::INTEGER FROM public.chat_members x
          WHERE x.group_id = m.group_id) AS member_count
    FROM public.chat_members m
    WHERE m.user_id = p_user_id;
$fn$;

-- Deny-by-default for browser roles; backend (service_role) keeps full access.
ALTER TABLE public.chat_groups     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_members    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_reactions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_poll_votes ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.chat_groups, public.chat_members, public.chat_messages,
              public.chat_reactions, public.chat_poll_votes
    FROM anon, authenticated;
GRANT ALL ON public.chat_groups, public.chat_members, public.chat_messages,
             public.chat_reactions, public.chat_poll_votes
    TO service_role;

REVOKE ALL ON FUNCTION public.chat_group_summaries(UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.chat_group_summaries(UUID) TO service_role;

-- Private bucket for chat media; served via short-lived signed URLs.
INSERT INTO storage.buckets (id, name, public)
VALUES ('chat-media', 'chat-media', false)
ON CONFLICT (id) DO NOTHING;

COMMIT;
