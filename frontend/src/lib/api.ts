// ============================================================
// Academix AI — Axios API Client
// Automatically attaches the Supabase JWT to every request
// ============================================================
import axios, { AxiosError } from 'axios'
import { supabase } from './supabase'
import toast from 'react-hot-toast'

/**
 * Resolve the API base URL. Every backend route lives under `/api`, so
 * VITE_API_URL may be given either as the bare backend origin
 * (`https://backend.up.railway.app`) or with the prefix already on it
 * (`https://backend.up.railway.app/api`) — both resolve to the same thing.
 * Unset, it falls back to `/api` on the current origin (the Vite dev proxy).
 */
function resolveBaseURL(): string {
  const raw = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '')
  if (!raw) return '/api'
  const withScheme = /^https?:\/\//i.test(raw) || raw.startsWith('/') ? raw : `https://${raw}`
  return withScheme.endsWith('/api') ? withScheme : `${withScheme}/api`
}

export const API_BASE_URL = resolveBaseURL()

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT access token from Supabase session on every request
api.interceptors.request.use(async (config) => {
  const { data: { session } } = await supabase.auth.getSession()
  if (session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`
  }
  return config
})

// Handle errors globally
api.interceptors.response.use(
  (response) => {
    // A static host answers unknown paths with index.html and a 200. If that
    // reaches the app it is silently treated as data (no user role, no course
    // list), so reject it loudly: the API URL is misconfigured.
    const contentType = String(response.headers?.['content-type'] || '')
    if (response.config.responseType !== 'blob' && contentType.includes('text/html')) {
      console.error(
        `[api] Expected JSON from ${response.config.baseURL}${response.config.url} but got HTML. ` +
        'Check that VITE_API_URL points at the backend service.'
      )
      return Promise.reject(new AxiosError(
        'API returned HTML instead of JSON — VITE_API_URL is misconfigured',
        'ERR_BAD_RESPONSE', response.config, response.request, response,
      ))
    }
    return response
  },
  (error: AxiosError<{ detail: string }>) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail || 'An unexpected error occurred'

    if (status === 401) {
      toast.error('Session expired. Please log in again.')
      supabase.auth.signOut()
      if (window.location.pathname !== '/login') window.location.href = '/login'
    } else if (status === 403) {
      toast.error('Access denied: ' + detail)
    } else if (status && status >= 500) {
      toast.error('Server error. Please try again.')
    } else if (!error.response) {
      toast.error('Cannot reach the server. Please try again.', { id: 'network-error' })
    }
    return Promise.reject(error)
  }
)

export default api
