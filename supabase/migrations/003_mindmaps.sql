-- Migration: 003_mindmaps
-- Creates the `mindmaps` table for the interactive drill-down mindmap feature.

CREATE TABLE public.mindmaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_id UUID NOT NULL REFERENCES public.content_documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    topic TEXT,
    tree_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Turn on RLS
ALTER TABLE public.mindmaps ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "Users can view their own mindmaps"
    ON public.mindmaps FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create their own mindmaps"
    ON public.mindmaps FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete their own mindmaps"
    ON public.mindmaps FOR DELETE
    USING (auth.uid() = user_id);
