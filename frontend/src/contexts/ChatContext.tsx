// ============================================================
// Academix AI — Chat real-time context
// One WebSocket per tab: keeps the group list + unread counts fresh
// app-wide (sidebar badge, toasts) and fans events out to the chat page.
// ============================================================
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import api from '@/lib/api'
import { supabase } from '@/lib/supabase'
import { useAuth } from '@/contexts/AuthContext'
import { chatSocketURL, messagePreview } from '@/lib/chat'
import type { ChatEvent, ChatGroup } from '@/lib/chat'

type Listener = (event: ChatEvent) => void

interface ChatContextType {
  groups: ChatGroup[]
  groupsLoading: boolean
  connected: boolean
  totalUnread: number
  refreshGroups: () => Promise<void>
  subscribe: (listener: Listener) => () => void
  sendTyping: (groupId: string) => void
  setActiveGroup: (groupId: string | null) => void
  markRead: (groupId: string) => void
}

const ChatContext = createContext<ChatContextType | null>(null)

const PING_MS = 25_000 // under Railway's/most proxies' idle timeout

export function ChatProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [groups, setGroups] = useState<ChatGroup[]>([])
  const [groupsLoading, setGroupsLoading] = useState(true)
  const [connected, setConnected] = useState(false)
  const groupsRef = useRef<ChatGroup[]>([])
  groupsRef.current = groups
  const listeners = useRef(new Set<Listener>())
  const wsRef = useRef<WebSocket | null>(null)
  const activeGroup = useRef<string | null>(null)
  const onChatPage = useRef(false)
  onChatPage.current = location.pathname.startsWith('/chat')

  const refreshGroups = useCallback(async () => {
    try {
      const { data } = await api.get('/chat/groups')
      const list: ChatGroup[] = Array.isArray(data) ? data : []
      // The open conversation is being read right now; a refetch can race the
      // mark-read request, so never show it as unread.
      const viewing = onChatPage.current && document.visibilityState === 'visible' ? activeGroup.current : null
      setGroups(list.map(g => g.id === viewing ? { ...g, unread_count: 0 } : g))
    } catch { /* toast handled globally */ }
    setGroupsLoading(false)
  }, [])

  const markRead = useCallback((groupId: string) => {
    setGroups(gs => gs.map(g => g.id === groupId ? { ...g, unread_count: 0 } : g))
    api.post(`/chat/groups/${groupId}/read`).catch(() => {})
  }, [])

  const handleEvent = useCallback((event: ChatEvent) => {
    if (event.type === 'message.new') {
      const m = event.message
      const mine = m.sender?.id === user?.id
      const viewing = activeGroup.current === m.group_id && onChatPage.current && document.visibilityState === 'visible'
      const known = groupsRef.current.some(g => g.id === m.group_id)
      setGroups(gs => {
        const idx = gs.findIndex(g => g.id === m.group_id)
        if (idx === -1) return gs
        const g = gs[idx]
        const updated: ChatGroup = {
          ...g,
          last_message: m,
          last_message_at: m.created_at,
          unread_count: mine || viewing ? 0 : (g.unread_count || 0) + 1,
        }
        return [updated, ...gs.slice(0, idx), ...gs.slice(idx + 1)]
      })
      if (!known) void refreshGroups()
      if (!mine && !viewing && m.kind !== 'system') {
        toast(t => (
          <div style={{ cursor: 'pointer', maxWidth: 280 }} onClick={() => { toast.dismiss(t.id); navigate(`/chat/${m.group_id}`) }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{m.is_important ? '❗ ' : '💬 '}New message</div>
            <div style={{ fontSize: 13, opacity: 0.85, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {messagePreview(m)}
            </div>
          </div>
        ), { id: `chat-${m.group_id}`, duration: 4000 })
      }
    } else if (event.type === 'message.updated') {
      setGroups(gs => gs.map(g => g.id === event.group_id && g.last_message?.id === event.message.id
        ? { ...g, last_message: event.message } : g))
    } else if (event.type === 'group.changed' || event.type === 'group.removed') {
      void refreshGroups()
    }
    listeners.current.forEach(l => { try { l(event) } catch (e) { console.error(e) } })
  }, [user?.id, refreshGroups, navigate])

  const handleRef = useRef(handleEvent)
  handleRef.current = handleEvent

  // Socket lifecycle with exponential backoff reconnect.
  useEffect(() => {
    if (!user) return
    let stopped = false
    let retry = 0
    let pingTimer: ReturnType<typeof setInterval> | undefined
    let retryTimer: ReturnType<typeof setTimeout> | undefined

    const connect = async () => {
      if (stopped) return
      const { data: { session } } = await supabase.auth.getSession()
      if (!session?.access_token || stopped) return
      let ws: WebSocket
      try {
        ws = new WebSocket(chatSocketURL())
      } catch {
        scheduleReconnect()
        return
      }
      wsRef.current = ws
      ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: session.access_token }))
      ws.onmessage = (e) => {
        let event: ChatEvent
        try { event = JSON.parse(e.data) } catch { return }
        if (event.type === 'ready') {
          retry = 0
          setConnected(true)
          // Catch up on anything missed while disconnected.
          void refreshGroups()
          listeners.current.forEach(l => l(event))
          clearInterval(pingTimer)
          pingTimer = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send('{"type":"ping"}')
          }, PING_MS)
          return
        }
        handleRef.current(event)
      }
      ws.onclose = () => {
        clearInterval(pingTimer)
        if (wsRef.current === ws) wsRef.current = null
        setConnected(false)
        scheduleReconnect()
      }
      ws.onerror = () => { /* onclose follows */ }
    }

    const scheduleReconnect = () => {
      if (stopped) return
      const delay = Math.min(30_000, 1000 * 2 ** retry) + Math.random() * 500
      retry += 1
      clearTimeout(retryTimer)
      retryTimer = setTimeout(connect, delay)
    }

    // Reconnect promptly when the tab comes back (laptops sleep, phones background).
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      if (!wsRef.current || wsRef.current.readyState > WebSocket.OPEN) {
        retry = 0
        clearTimeout(retryTimer)
        void connect()
      } else {
        void refreshGroups()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    void refreshGroups()
    void connect()

    return () => {
      stopped = true
      clearInterval(pingTimer)
      clearTimeout(retryTimer)
      document.removeEventListener('visibilitychange', onVisible)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [user?.id, refreshGroups])

  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener)
    return () => { listeners.current.delete(listener) }
  }, [])

  const lastTyping = useRef(0)
  const sendTyping = useCallback((groupId: string) => {
    const now = Date.now()
    if (now - lastTyping.current < 3000) return
    lastTyping.current = now
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'typing', group_id: groupId }))
  }, [])

  const setActiveGroup = useCallback((groupId: string | null) => { activeGroup.current = groupId }, [])

  const totalUnread = useMemo(() => groups.reduce((n, g) => n + (g.unread_count || 0), 0), [groups])

  return (
    <ChatContext.Provider value={{
      groups, groupsLoading, connected, totalUnread, refreshGroups,
      subscribe, sendTyping, setActiveGroup, markRead,
    }}>
      {children}
    </ChatContext.Provider>
  )
}

export function useChat() {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useChat must be used within ChatProvider')
  return ctx
}
