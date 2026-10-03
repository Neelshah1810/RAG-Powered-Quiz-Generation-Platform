// ============================================================
// Academix AI — Group chat types + helpers
// ============================================================
import { API_BASE_URL } from './api'

export type PostPolicy = 'admins' | 'everyone'
export type GroupRole = 'admin' | 'member'

export interface ChatAttachment {
  path: string
  name: string
  size: number
  mime: string
  url?: string | null
}

export interface ChatPollOption {
  id: string
  text: string
  voter_ids: string[]
}

export interface ChatPoll {
  question: string
  allow_multiple: boolean
  closed: boolean
  options: ChatPollOption[]
}

export interface ChatMessage {
  id: string
  group_id: string
  kind: 'text' | 'poll' | 'system'
  body: string | null
  attachments: ChatAttachment[]
  is_important: boolean
  poll: ChatPoll | null
  created_at: string
  deleted: boolean
  sender: { id: string; full_name: string; role?: string } | null
  /** emoji -> user ids */
  reactions: Record<string, string[]>
}

export interface ChatGroup {
  id: string
  name: string
  description?: string | null
  course_id?: string | null
  course_code?: string | null
  course_name?: string | null
  post_policy: PostPolicy
  color: string
  created_by?: string | null
  created_at?: string
  last_message_at?: string
  my_role: GroupRole | null
  can_post: boolean
  unread_count?: number
  member_count?: number
  last_message?: ChatMessage | null
}

export interface ChatMember {
  user_id: string
  full_name: string
  email?: string
  role?: 'admin' | 'teacher' | 'student'
  group_role: GroupRole
}

export interface ChatGroupDetail extends ChatGroup {
  members: ChatMember[]
}

export interface DirectoryUser {
  id: string
  full_name: string
  email: string
  role: 'admin' | 'teacher' | 'student'
  courses: string[]
}

export interface ScopeCourse {
  id: string
  name: string
  code: string
  semester?: number | null
}

export type ChatEvent =
  | { type: 'ready'; user_id: string }
  | { type: 'pong' }
  | { type: 'message.new'; group_id: string; message: ChatMessage }
  | { type: 'message.updated'; group_id: string; message: ChatMessage }
  | { type: 'group.changed'; group_id: string }
  | { type: 'group.removed'; group_id: string }
  | { type: 'typing'; group_id: string; user_id: string; name: string }

export const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🙏', '🎉', '✅']

/** ws(s)://<backend>/api/chat/ws, derived from the REST base URL. */
export function chatSocketURL(): string {
  if (/^https?:\/\//i.test(API_BASE_URL)) {
    return API_BASE_URL.replace(/^http/i, 'ws') + '/chat/ws'
  }
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}${API_BASE_URL}/chat/ws`
}

export function messagePreview(m?: ChatMessage | null): string {
  if (!m) return 'No messages yet'
  if (m.deleted) return 'This message was deleted'
  if (m.kind === 'system') return m.body || ''
  const who = m.sender ? `${m.sender.full_name.split(' ')[0]}: ` : ''
  if (m.kind === 'poll') return `${who}📊 ${m.poll?.question || 'Poll'}`
  if (m.body) return who + m.body
  if (m.attachments.length) {
    const a = m.attachments[0]
    const icon = a.mime.startsWith('image/') ? '📷' : a.mime.startsWith('video/') ? '🎬' : '📎'
    return `${who}${icon} ${m.attachments.length > 1 ? `${m.attachments.length} files` : a.name}`
  }
  return who
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function initials(name?: string | null): string {
  const parts = (name || '?').trim().split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] || '?') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase()
}

/** Human-readable message from a FastAPI error response. */
export function errorDetail(err: any, fallback: string): string {
  const d = err?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && d[0]?.msg) return d[0].msg
  return fallback
}
