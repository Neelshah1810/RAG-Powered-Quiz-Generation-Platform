"""
Academix AI — Supabase Client Initialization

Provides two clients:
  - `get_supabase()` — uses anon key (respects RLS, for user-context requests)
  - `get_supabase_admin()` — uses service_role key (bypasses RLS, for server-side operations)
"""

from supabase import create_client, Client
from functools import lru_cache
from app.config import get_settings


@lru_cache()
def get_supabase() -> Client:
    """
    Supabase client with anon key.
    Use for operations that should respect Row Level Security.
    """
    settings = get_settings()
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


@lru_cache()
def get_supabase_admin() -> Client:
    """
    Supabase client with service_role key.
    Bypasses RLS — use ONLY for server-side operations like:
      - Ingestion pipeline (inserting chunks/embeddings)
      - Admin operations (creating users, managing courses)
      - Background tasks
    """
    settings = get_settings()
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
