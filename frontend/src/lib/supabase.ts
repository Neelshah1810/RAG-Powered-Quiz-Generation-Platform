// ============================================================
// Academix AI — Supabase Client (Frontend)
// ============================================================
import { createClient } from '@supabase/supabase-js'

// TODO: These values come from your .env file (copy .env.example → .env)
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error(
    'Missing Supabase environment variables. Copy .env.example to .env and fill in your values.'
  )
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    storageKey: 'academix-auth',
  },
})
