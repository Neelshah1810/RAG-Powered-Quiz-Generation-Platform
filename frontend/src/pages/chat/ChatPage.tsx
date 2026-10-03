// ============================================================
// Academix AI — Group Chat (Teams/WhatsApp-style)
// Left: my groups · Centre: conversation · Right: group info
// ============================================================
import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { format, isToday, isYesterday } from 'date-fns'
import toast from 'react-hot-toast'
import {
  AlertCircle, ArrowLeft, BarChart3, Info, Loader2, Lock, LogOut, Megaphone,
  MessagesSquare, Paperclip, Plus, Search, Send, Trash2, UserMinus, UserPlus, X,
} from 'lucide-react'
import api from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'
import { useChat } from '@/contexts/ChatContext'
import { errorDetail, formatBytes, initials, messagePreview } from '@/lib/chat'
import type { ChatAttachment, ChatEvent, ChatGroup, ChatGroupDetail, ChatMessage, PostPolicy } from '@/lib/chat'
import MessageItem from '@/components/chat/MessageItem'
import { AddMembersModal, CreateGroupModal, PolicyPicker, PollModal } from '@/components/chat/ChatModals'

const PAGE = 50
const MAX_FILE_MB = 50

function listTime(iso?: string) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isToday(d)) return format(d, 'h:mm a')
  if (isYesterday(d)) return 'Yesterday'
  return format(d, 'dd/MM/yy')
}

function dayLabel(d: Date) {
  if (isToday(d)) return 'Today'
  if (isYesterday(d)) return 'Yesterday'
  return format(d, 'EEEE, d MMMM yyyy')
}

function toastError(err: any, fallback: string) {
  const s = err?.response?.status
  // 403 and 5xx are already toasted by the API client.
  if (s === 403 || (s && s >= 500)) return
  toast.error(errorDetail(err, fallback))
}

export default function ChatPage() {
  const { groupId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const { groups, groupsLoading, connected, refreshGroups } = useChat()
  const [filter, setFilter] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const isStaff = user?.role === 'teacher' || user?.role === 'admin'

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return q ? groups.filter(g => g.name.toLowerCase().includes(q) || (g.course_code || '').toLowerCase().includes(q)) : groups
  }, [groups, filter])

  const active = groups.find(g => g.id === groupId) || null
  const onGroupGone = useCallback(() => { void refreshGroups(); navigate('/chat') }, [refreshGroups, navigate])

  // A stale or foreign group id in the URL: bounce back to the list.
  useEffect(() => {
    if (groupId && !groupsLoading && !groups.some(g => g.id === groupId)) navigate('/chat', { replace: true })
  }, [groupId, groups, groupsLoading, navigate])

  return (
    <div>
      <div className={`cx-layout ${groupId ? 'has-active' : ''}`}>
        {/* ── Group list ── */}
        <aside className="cx-list">
          <div className="cx-list-header">
            <div className="flex-between">
              <h2 style={{ fontSize: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
                Chat
                <span title={connected ? 'Live' : 'Reconnecting…'} style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: connected ? 'var(--color-secondary)' : 'var(--color-warning)',
                }} />
              </h2>
              {isStaff && (
                <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>
                  <Plus size={16} /> New group
                </button>
              )}
            </div>
            <div style={{ position: 'relative' }}>
              <Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-3)' }} />
              <input className="input" placeholder="Search groups" value={filter} onChange={e => setFilter(e.target.value)} style={{ paddingLeft: 36, borderRadius: 20 }} />
            </div>
          </div>

          <div className="cx-list-items">
            {groupsLoading && [1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 56, margin: '10px 16px' }} />)}
            {!groupsLoading && visible.length === 0 && (
              <div className="text-muted" style={{ padding: 24, fontSize: 13, textAlign: 'center' }}>
                {groups.length === 0
                  ? (isStaff ? 'No groups yet. Create one to start chatting with your class.' : "You haven't been added to any group yet.")
                  : 'No groups match your search.'}
              </div>
            )}
            {visible.map(g => <GroupListItem key={g.id} group={g} active={g.id === groupId} onClick={() => navigate(`/chat/${g.id}`)} />)}
          </div>
        </aside>

        {/* ── Conversation ── */}
        {active ? (
          <Thread key={active.id} group={active} onGroupGone={onGroupGone} />
        ) : (
          <div className="cx-thread"><div className="cx-empty">
            <MessagesSquare size={56} color="var(--color-primary)" />
            <h3>Academix Chat</h3>
            <p style={{ maxWidth: 360, fontSize: 14 }}>
              {isStaff
                ? 'Send announcements, files and polls to your classes. Pick a group or create a new one.'
                : 'Announcements, files and polls from your teachers show up here.'}
            </p>
          </div></div>
        )}
      </div>

      {showCreate && (
        <CreateGroupModal
          onClose={() => setShowCreate(false)}
          onCreated={async g => { setShowCreate(false); await refreshGroups(); navigate(`/chat/${g.id}`) }}
        />
      )}
    </div>
  )
}

function GroupListItem({ group: g, active, onClick }: { group: ChatGroup; active: boolean; onClick: () => void }) {
  const unread = g.unread_count || 0
  return (
    <div className={`cx-group-item ${active ? 'active' : ''}`} onClick={onClick}>
      <div className="cx-group-avatar" style={{ background: g.color }}>{initials(g.name)}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="flex-between" style={{ gap: 8 }}>
          <span className="cx-ellipsis" style={{ fontWeight: unread ? 700 : 500, fontSize: 14 }}>
            {g.post_policy === 'admins' && <Megaphone size={12} className="cx-inline-icon" color="var(--color-text-3)" />}
            {g.name}
          </span>
          <span style={{ fontSize: 11, color: unread ? 'var(--color-primary)' : 'var(--color-text-3)', flexShrink: 0 }}>
            {listTime(g.last_message?.created_at || g.last_message_at)}
          </span>
        </div>
        <div className="flex-between" style={{ gap: 8, marginTop: 2 }}>
          <span className="cx-ellipsis text-muted" style={{ fontSize: 13, fontWeight: unread ? 600 : 400 }}>
            {g.last_message?.is_important && <AlertCircle size={12} color="var(--color-danger)" className="cx-inline-icon" />}
            {messagePreview(g.last_message)}
          </span>
          {unread > 0 && <span className="cx-unread">{unread > 99 ? '99+' : unread}</span>}
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Thread
// ─────────────────────────────────────────────────────────────

function Thread({ group, onGroupGone }: { group: ChatGroup; onGroupGone: () => void }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { subscribe, setActiveGroup, markRead, sendTyping } = useChat()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [hasMore, setHasMore] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [detail, setDetail] = useState<ChatGroupDetail | null>(null)
  const [showInfo, setShowInfo] = useState(false)
  const [typing, setTyping] = useState<Record<string, { name: string; until: number }>>({})
  const [lightbox, setLightbox] = useState<string | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)
  const restoreFrom = useRef<number | null>(null)
  const meId = user?.id || ''
  const isGroupAdmin = group.my_role === 'admin'

  const loadDetail = useCallback(() => {
    api.get(`/chat/groups/${group.id}`).then(r => setDetail(r.data)).catch(() => {})
  }, [group.id])

  const loadLatest = useCallback(async () => {
    try {
      const { data } = await api.get(`/chat/groups/${group.id}/messages`, { params: { limit: PAGE } })
      const list: ChatMessage[] = Array.isArray(data) ? data : []
      stickToBottom.current = true
      setMessages(list)
      setHasMore(list.length === PAGE)
    } catch (err: any) {
      if (err?.response?.status === 404) onGroupGone()
    } finally {
      setLoading(false)
    }
  }, [group.id, onGroupGone])

  useEffect(() => {
    setActiveGroup(group.id)
    void loadLatest()
    loadDetail()
    markRead(group.id)
    return () => setActiveGroup(null)
  }, [group.id, setActiveGroup, loadLatest, loadDetail, markRead])

  // Real-time events for this group.
  useEffect(() => subscribe((e: ChatEvent) => {
    if (e.type === 'ready') { void loadLatest(); return }  // reconnected: catch up
    if (!('group_id' in e) || e.group_id !== group.id) return
    if (e.type === 'message.new') {
      const el = scroller.current
      stickToBottom.current = !el || el.scrollHeight - el.scrollTop - el.clientHeight < 120 || e.message.sender?.id === meId
      setMessages(ms => ms.some(m => m.id === e.message.id) ? ms : [...ms, e.message])
      if (e.message.sender) setTyping(t => { const n = { ...t }; delete n[e.message.sender!.id]; return n })
      if (document.visibilityState === 'visible') markRead(group.id)
    } else if (e.type === 'message.updated') {
      setMessages(ms => ms.map(m => m.id === e.message.id ? e.message : m))
    } else if (e.type === 'group.changed') {
      loadDetail()
    } else if (e.type === 'group.removed') {
      toast('You are no longer a member of this group')
      onGroupGone()
    } else if (e.type === 'typing') {
      setTyping(t => ({ ...t, [e.user_id]: { name: e.name, until: Date.now() + 4000 } }))
    }
  }), [subscribe, group.id, meId, markRead, loadDetail, loadLatest, onGroupGone])

  // Expire typing indicators.
  useEffect(() => {
    if (!Object.keys(typing).length) return
    const t = setInterval(() => {
      setTyping(cur => {
        const now = Date.now()
        const next = Object.fromEntries(Object.entries(cur).filter(([, v]) => v.until > now))
        return Object.keys(next).length === Object.keys(cur).length ? cur : next
      })
    }, 1000)
    return () => clearInterval(t)
  }, [typing])

  // Mark read when the tab regains focus.
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === 'visible') markRead(group.id) }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [group.id, markRead])

  // Scroll management: stick to bottom for new messages, keep position when loading older.
  useLayoutEffect(() => {
    const el = scroller.current
    if (!el) return
    if (restoreFrom.current !== null) {
      el.scrollTop = el.scrollHeight - restoreFrom.current
      restoreFrom.current = null
    } else if (stickToBottom.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages])

  const loadOlder = async () => {
    if (!messages.length || loadingOlder) return
    setLoadingOlder(true)
    try {
      const { data } = await api.get(`/chat/groups/${group.id}/messages`, { params: { before: messages[0].created_at, limit: PAGE } })
      const older: ChatMessage[] = Array.isArray(data) ? data : []
      const el = scroller.current
      restoreFrom.current = el ? el.scrollHeight - el.scrollTop : null
      stickToBottom.current = false
      setMessages(ms => [...older.filter(o => !ms.some(m => m.id === o.id)), ...ms])
      setHasMore(older.length === PAGE)
    } catch { /* toasted */ }
    setLoadingOlder(false)
  }

  const onScroll = () => {
    const el = scroller.current
    if (!el) return
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    if (el.scrollTop < 60 && hasMore && !loadingOlder) void loadOlder()
  }

  // Images/videos grow the list after layout; keep the view pinned to the bottom.
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const onMediaLoad = () => { if (stickToBottom.current) el.scrollTop = el.scrollHeight }
    el.addEventListener('load', onMediaLoad, true)
    el.addEventListener('loadedmetadata', onMediaLoad, true)
    return () => {
      el.removeEventListener('load', onMediaLoad, true)
      el.removeEventListener('loadedmetadata', onMediaLoad, true)
    }
  }, [])

  const replace = (m: ChatMessage) => setMessages(ms => ms.map(x => x.id === m.id ? m : x))

  const onReact = useCallback(async (m: ChatMessage, emoji: string | null) => {
    try { replace((await api.put(`/chat/messages/${m.id}/reaction`, { emoji })).data) } catch (err) { toastError(err, 'Could not react') }
  }, [])
  const onVote = useCallback(async (m: ChatMessage, option_ids: string[]) => {
    try { replace((await api.post(`/chat/messages/${m.id}/vote`, { option_ids })).data) } catch (err) { toastError(err, 'Could not vote') }
  }, [])
  const onClosePoll = useCallback(async (m: ChatMessage) => {
    try { replace((await api.post(`/chat/messages/${m.id}/close-poll`)).data) } catch (err) { toastError(err, 'Could not close poll') }
  }, [])
  const onDelete = useCallback(async (m: ChatMessage) => {
    if (!window.confirm('Delete this message for everyone?')) return
    try { replace((await api.delete(`/chat/messages/${m.id}`)).data) } catch (err) { toastError(err, 'Could not delete') }
  }, [])

  const appendOwn = (m: ChatMessage) => {
    stickToBottom.current = true
    setMessages(ms => ms.some(x => x.id === m.id) ? ms : [...ms, m])
  }

  const typingNames = Object.values(typing).map(t => t.name.split(' ')[0])

  return (
    <>
      <section className="cx-thread">
        <header className="cx-thread-header">
          <button className="btn btn-ghost btn-icon" onClick={() => navigate('/chat')} title="Back"><ArrowLeft size={18} /></button>
          <div className="cx-group-avatar" style={{ background: group.color, width: 38, height: 38 }}>{initials(group.name)}</div>
          <div style={{ flex: 1, minWidth: 0, cursor: 'pointer' }} onClick={() => setShowInfo(s => !s)}>
            <div className="font-semibold cx-ellipsis">{group.name}</div>
            <div className="text-muted cx-ellipsis" style={{ fontSize: 12 }}>
              {typingNames.length
                ? <span style={{ color: 'var(--color-secondary)' }}>{typingNames.join(', ')} typing…</span>
                : <>
                    {detail?.member_count ?? group.member_count ?? '–'} members
                    {group.course_code ? ` · ${group.course_code}` : ''}
                    {group.post_policy === 'admins' ? ' · Only teachers/admins can send' : ''}
                  </>}
            </div>
          </div>
          <button className={`btn btn-icon ${showInfo ? 'btn-secondary' : 'btn-ghost'}`} onClick={() => setShowInfo(s => !s)} title="Group info"><Info size={18} /></button>
        </header>

        <div className="cx-messages" ref={scroller} onScroll={onScroll}>
          {loading && <div className="flex-center" style={{ flex: 1 }}><Loader2 className="spin" size={28} color="var(--color-primary)" /></div>}
          {!loading && hasMore && (
            <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'center' }} onClick={loadOlder} disabled={loadingOlder}>
              {loadingOlder ? 'Loading…' : 'Load older messages'}
            </button>
          )}
          {!loading && messages.map((m, i) => {
            const prev = messages[i - 1]
            const d = new Date(m.created_at)
            const newDay = !prev || new Date(prev.created_at).toDateString() !== d.toDateString()
            const continuation = !newDay && !!prev && prev.kind !== 'system' && m.kind !== 'system'
              && prev.sender?.id === m.sender?.id && d.getTime() - new Date(prev.created_at).getTime() < 5 * 60_000
            return (
              <Fragment key={m.id}>
                {newDay && <div className="cx-day">{dayLabel(d)}</div>}
                <MessageItem
                  message={m} meId={meId} isGroupAdmin={isGroupAdmin} continuation={continuation}
                  onReact={onReact} onVote={onVote} onClosePoll={onClosePoll} onDelete={onDelete} onOpenImage={setLightbox}
                />
              </Fragment>
            )
          })}
        </div>

        {group.can_post ? (
          <Composer group={group} isGroupAdmin={isGroupAdmin} onSent={appendOwn} onTyping={() => sendTyping(group.id)} />
        ) : (
          <div className="cx-readonly">
            <Lock size={16} /> Only teachers and admins can send messages in this group. You can react to messages and vote in polls.
          </div>
        )}
      </section>

      {showInfo && detail && (
        <GroupInfo detail={detail} onClose={() => setShowInfo(false)} onChanged={setDetail} onGone={onGroupGone} />
      )}

      {lightbox && <div className="cx-lightbox" onClick={() => setLightbox(null)}><img src={lightbox} alt="" /></div>}
    </>
  )
}

// ─────────────────────────────────────────────────────────────
// Composer
// ─────────────────────────────────────────────────────────────

interface Pending { id: string; file: File; status: 'uploading' | 'done' | 'error'; progress: number; result?: ChatAttachment }

function Composer({ group, isGroupAdmin, onSent, onTyping }: {
  group: ChatGroup; isGroupAdmin: boolean; onSent: (m: ChatMessage) => void; onTyping: () => void
}) {
  const [text, setText] = useState('')
  const [important, setImportant] = useState(false)
  const [pending, setPending] = useState<Pending[]>([])
  const [sending, setSending] = useState(false)
  const [showPoll, setShowPoll] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)

  const uploading = pending.some(p => p.status === 'uploading')
  const ready = pending.filter(p => p.status === 'done' && p.result)
  const canSend = !sending && !uploading && (text.trim().length > 0 || ready.length > 0)

  const upload = (files: FileList | File[]) => {
    const list = Array.from(files).slice(0, 10 - pending.length)
    for (const file of list) {
      if (file.size > MAX_FILE_MB * 1024 * 1024) { toast.error(`${file.name} is larger than ${MAX_FILE_MB} MB`); continue }
      const id = Math.random().toString(36).slice(2)
      setPending(p => [...p, { id, file, status: 'uploading', progress: 0 }])
      const form = new FormData()
      form.append('file', file)
      api.post(`/chat/groups/${group.id}/attachments`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: e => setPending(p => p.map(x => x.id === id ? { ...x, progress: e.total ? Math.round((e.loaded / e.total) * 100) : 0 } : x)),
      })
        .then(r => setPending(p => p.map(x => x.id === id ? { ...x, status: 'done', progress: 100, result: r.data } : x)))
        .catch(err => {
          toastError(err, `Could not upload ${file.name}`)
          setPending(p => p.map(x => x.id === id ? { ...x, status: 'error' } : x))
        })
    }
  }

  const send = async () => {
    if (!canSend) return
    setSending(true)
    try {
      const { data } = await api.post(`/chat/groups/${group.id}/messages`, {
        body: text.trim() || null,
        attachments: ready.map(p => p.result),
        is_important: important,
      })
      onSent(data)
      setText(''); setPending([]); setImportant(false)
      textarea.current?.focus()
    } catch (err) {
      toastError(err, 'Message not sent')
    } finally {
      setSending(false)
    }
  }

  const sendPoll = async (poll: { question: string; options: string[]; allow_multiple: boolean }) => {
    try {
      const { data } = await api.post(`/chat/groups/${group.id}/messages`, { poll, is_important: important })
      onSent(data)
      setImportant(false)
      return true
    } catch (err) {
      toastError(err, 'Poll not sent')
      return false
    }
  }

  // Auto-grow the textarea.
  useLayoutEffect(() => {
    const el = textarea.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 140) + 'px'
  }, [text])

  return (
    <div
      className="cx-composer"
      onDragOver={e => { e.preventDefault() }}
      onDrop={e => { e.preventDefault(); if (e.dataTransfer.files.length) upload(e.dataTransfer.files) }}
    >
      {pending.length > 0 && (
        <div className="cx-pending">
          {pending.map(p => (
            <span key={p.id} className="cx-chip" style={p.status === 'error' ? { borderColor: 'var(--color-danger)', color: 'var(--color-danger)' } : undefined}>
              {p.status === 'uploading' && <Loader2 size={12} className="spin" />}
              <span className="cx-ellipsis" style={{ maxWidth: 160 }}>{p.file.name}</span>
              <span className="text-muted" style={{ fontSize: 11 }}>{p.status === 'uploading' ? `${p.progress}%` : p.status === 'error' ? 'failed' : formatBytes(p.file.size)}</span>
              <button style={{ border: 'none', background: 'none', cursor: 'pointer', display: 'flex', padding: 0 }} onClick={() => setPending(ps => ps.filter(x => x.id !== p.id))}><X size={13} /></button>
            </span>
          ))}
        </div>
      )}
      {important && (
        <div className="cx-important-tag" style={{ marginBottom: 6 }}>
          <AlertCircle size={13} /> This message will be marked as IMPORTANT
        </div>
      )}
      <div className="cx-composer-row">
        <input ref={fileInput} type="file" multiple hidden onChange={e => { if (e.target.files) upload(e.target.files); e.target.value = '' }} />
        <button className="btn btn-ghost btn-icon" title="Attach files, images or videos" onClick={() => fileInput.current?.click()}><Paperclip size={18} /></button>
        <button className="btn btn-ghost btn-icon" title="Create poll" onClick={() => setShowPoll(true)}><BarChart3 size={18} /></button>
        {isGroupAdmin && (
          <button
            className="btn btn-icon"
            title="Mark as important"
            onClick={() => setImportant(i => !i)}
            style={{ background: important ? '#FCE8E6' : 'transparent', color: important ? 'var(--color-danger)' : 'var(--color-text-2)' }}
          >
            <AlertCircle size={18} />
          </button>
        )}
        <textarea
          ref={textarea}
          className="cx-textarea"
          rows={1}
          placeholder="Type a message"
          value={text}
          maxLength={5000}
          onChange={e => { setText(e.target.value); onTyping() }}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send() } }}
          onPaste={e => { if (e.clipboardData.files.length) { e.preventDefault(); upload(e.clipboardData.files) } }}
        />
        <button className="btn btn-primary btn-icon" style={{ borderRadius: '50%', width: 42, height: 42, padding: 0, justifyContent: 'center' }} onClick={send} disabled={!canSend} title="Send">
          {sending ? <Loader2 size={18} className="spin" /> : <Send size={18} />}
        </button>
      </div>
      {showPoll && <PollModal onClose={() => setShowPoll(false)} onSubmit={sendPoll} />}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// Group info panel
// ─────────────────────────────────────────────────────────────

function GroupInfo({ detail, onClose, onChanged, onGone }: {
  detail: ChatGroupDetail; onClose: () => void; onChanged: (d: ChatGroupDetail) => void; onGone: () => void
}) {
  const { user } = useAuth()
  const { refreshGroups } = useChat()
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(detail.name)
  const [description, setDescription] = useState(detail.description || '')
  const isAdmin = detail.my_role === 'admin'
  const canDelete = user?.role === 'admin' || detail.created_by === user?.id
  const isStaff = user?.role === 'teacher' || user?.role === 'admin'

  const patch = async (body: Partial<{ name: string; description: string; post_policy: PostPolicy }>) => {
    try {
      const { data } = await api.patch(`/chat/groups/${detail.id}`, body)
      onChanged(data)
      void refreshGroups()
      return true
    } catch (err) {
      toastError(err, 'Could not update group')
      return false
    }
  }

  const removeMember = async (userId: string, label: string) => {
    if (!window.confirm(`Remove ${label} from the group?`)) return
    try {
      const { data } = await api.delete(`/chat/groups/${detail.id}/members/${userId}`)
      if (data?.members) onChanged(data)
    } catch (err) { toastError(err, 'Could not remove member') }
  }

  const leave = async () => {
    if (!window.confirm('Leave this group?')) return
    try {
      await api.delete(`/chat/groups/${detail.id}/members/${user?.id}`)
      toast.success('You left the group')
      onGone()
    } catch (err) { toastError(err, 'Could not leave group') }
  }

  const remove = async () => {
    if (!window.confirm(`Delete "${detail.name}" and all its messages for everyone? This cannot be undone.`)) return
    try {
      await api.delete(`/chat/groups/${detail.id}`)
      toast.success('Group deleted')
      onGone()
    } catch (err) { toastError(err, 'Could not delete group') }
  }

  return (
    <aside className="cx-info">
      <div className="cx-info-section flex-between">
        <h3 style={{ fontSize: 16 }}>Group info</h3>
        <button className="btn btn-ghost btn-icon" onClick={onClose}><X size={18} /></button>
      </div>

      <div className="cx-info-section" style={{ textAlign: 'center' }}>
        <div className="cx-group-avatar" style={{ background: detail.color, width: 64, height: 64, fontSize: 22, margin: '0 auto 10px', borderRadius: 18 }}>{initials(detail.name)}</div>
        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, textAlign: 'left' }}>
            <input className="input" value={name} maxLength={80} onChange={e => setName(e.target.value)} />
            <input className="input" value={description} maxLength={500} placeholder="Description" onChange={e => setDescription(e.target.value)} />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary btn-sm" onClick={() => setEditing(false)}>Cancel</button>
              <button className="btn btn-primary btn-sm" disabled={!name.trim()} onClick={async () => { if (await patch({ name: name.trim(), description })) setEditing(false) }}>Save</button>
            </div>
          </div>
        ) : (
          <>
            <div className="font-semibold" style={{ fontSize: 17 }}>{detail.name}</div>
            {detail.description && <p className="text-muted" style={{ fontSize: 13, marginTop: 4 }}>{detail.description}</p>}
            {detail.course_code && <span className="badge badge-blue" style={{ marginTop: 8 }}>{detail.course_code} · {detail.course_name}</span>}
            {isAdmin && <div><button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={() => setEditing(true)}>Edit name & description</button></div>}
          </>
        )}
      </div>

      <div className="cx-info-section">
        <div className="font-medium" style={{ fontSize: 14, marginBottom: 8 }}>Who can send messages</div>
        {isAdmin ? (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <PolicyPicker value={detail.post_policy} onChange={v => { if (v !== detail.post_policy) void patch({ post_policy: v }) }} />
          </div>
        ) : (
          <div className="text-muted" style={{ fontSize: 13 }}>
            {detail.post_policy === 'admins' ? 'Only teachers and admins' : 'Everyone in the group'}
          </div>
        )}
      </div>

      <div className="cx-info-section">
        <div className="flex-between" style={{ marginBottom: 8 }}>
          <div className="font-medium" style={{ fontSize: 14 }}>{detail.members.length} members</div>
          {isAdmin && <button className="btn btn-ghost btn-sm" onClick={() => setShowAdd(true)}><UserPlus size={15} /> Add</button>}
        </div>
        {detail.members.map(m => (
          <div key={m.user_id} className="cx-member">
            <div className="cx-avatar-sm" style={{ background: m.role === 'student' ? '#5C6BC0' : '#7B1FA2' }}>{initials(m.full_name)}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="cx-ellipsis" style={{ fontSize: 14 }}>{m.full_name}{m.user_id === user?.id ? ' (You)' : ''}</div>
              <div className="text-muted" style={{ fontSize: 11, textTransform: 'capitalize' }}>{m.role}</div>
            </div>
            {m.group_role === 'admin' && <span className="badge badge-green" style={{ fontSize: 10 }}>Group admin</span>}
            {isAdmin && m.user_id !== user?.id && (
              <button className="btn btn-ghost btn-icon" title="Remove" onClick={() => removeMember(m.user_id, m.full_name)}><UserMinus size={15} /></button>
            )}
          </div>
        ))}
      </div>

      <div className="cx-info-section" style={{ display: 'flex', flexDirection: 'column', gap: 8, borderBottom: 'none' }}>
        {isStaff && (
          <button className="btn btn-secondary" onClick={leave} style={{ justifyContent: 'center' }}><LogOut size={16} /> Leave group</button>
        )}
        {canDelete && (
          <button className="btn btn-danger" onClick={remove} style={{ justifyContent: 'center' }}><Trash2 size={16} /> Delete group</button>
        )}
      </div>

      {showAdd && <AddMembersModal group={detail} onClose={() => setShowAdd(false)} onDone={d => { setShowAdd(false); onChanged(d) }} />}
    </aside>
  )
}
