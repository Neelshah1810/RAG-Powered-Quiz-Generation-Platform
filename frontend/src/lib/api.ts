// ============================================================
// Academix AI — Axios API Client
// Automatically attaches the Supabase JWT to every request
// ============================================================
import axios, { AxiosError } from 'axios'
import { supabase } from './supabase'
import toast from 'react-hot-toast'

const api = axios.create({
  baseURL: '/api',
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
  (response) => response,
  (error: AxiosError<{ detail: string }>) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail || 'An unexpected error occurred'

    if (status === 401) {
      toast.error('Session expired. Please log in again.')
      supabase.auth.signOut()
      window.location.href = '/login'
    } else if (status === 403) {
      toast.error('Access denied: ' + detail)
    } else if (status && status >= 500) {
      toast.error('Server error. Please try again.')
    }
    return Promise.reject(error)
  }
)

export default api
