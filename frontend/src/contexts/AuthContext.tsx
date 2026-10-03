// ============================================================
// Academix AI — Auth Context
// Manages authentication state via Supabase Auth
// ============================================================
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { supabase } from '@/lib/supabase'
import api from '@/lib/api'
import type { User } from '@/lib/types'

interface AuthContextType {
  user: User | null
  isLoading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | null>(null)

const ROLES: ReadonlyArray<User['role']> = ['admin', 'teacher', 'student']

/** Accept only a real profile object — never an HTML page or an empty body. */
function toUser(data: unknown): User | null {
  if (!data || typeof data !== 'object') return null
  const p = data as Partial<User>
  if (!p.id || !p.role || !ROLES.includes(p.role)) return null
  const email = p.email || ''
  return {
    ...p,
    id: p.id,
    role: p.role,
    email,
    full_name: (p.full_name || '').trim() || email.split('@')[0] || 'User',
  } as User
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Fetch user profile from backend
  const fetchProfile = async (): Promise<User | null> => {
    try {
      const { data } = await api.get('/auth/me')
      const profile = toUser(data)
      if (!profile) console.error('[auth] /auth/me returned an invalid profile:', data)
      setUser(profile)
      return profile
    } catch {
      setUser(null)
      return null
    }
  }

  useEffect(() => {
    // Check existing session on mount
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        fetchProfile().finally(() => setIsLoading(false))
      } else {
        setIsLoading(false)
      }
    })

    // Listen for auth state changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, session) => {
        if (event === 'SIGNED_IN' && session) {
          // Supabase holds an auth lock while this callback runs; calling back
          // into supabase.auth (the API client reads the session) inside it can
          // deadlock, so defer the profile fetch until the callback returns.
          setTimeout(() => { void fetchProfile() }, 0)
        } else if (event === 'SIGNED_OUT') {
          setUser(null)
        }
      }
    )

    return () => subscription.unsubscribe()
  }, [])

  const signIn = async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
    const profile = await fetchProfile()
    if (!profile) {
      await supabase.auth.signOut()
      throw new Error('Signed in, but your profile could not be loaded. Please try again or contact an administrator.')
    }
  }

  const signOut = async () => {
    await supabase.auth.signOut()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
