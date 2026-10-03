// ============================================================
// Academix AI — One chat message (bubble, media, poll, reactions)
// ============================================================
import { memo, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { format } from 'date-fns'
import { AlertCircle, BarChart3, FileText, Lock, SmilePlus, Trash2 } from 'lucide-react'
import { QUICK_REACTIONS, formatBytes, initials } from '@/lib/chat'
import type { ChatAttachment, ChatMessage } from '@/lib/chat'

interface Props {
  message: ChatMessage
  meId: string
  isGroupAdmin: boolean
  /** Same sender as the previous message within a few minutes — compact layout. */
  continuation: boolean
  onReact: (message: ChatMessage, emoji: string | null) => void
  onVote: (message: ChatMessage, optionIds: string[]) => void
  onClosePoll: (message: ChatMessage) => void
  onDelete: (message: ChatMessage) => void
  onOpenImage: (url: string) => void
}

const URL_RE = /(https?:\/\/[^\s<]+)/g

function Linkified({ text }: { text: string }) {
  const parts = text.split(URL_RE)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1
          ? <a key={i} href={part} target="_blank" rel="noopener noreferrer">{part}</a>
          : <span key={i}>{part}</span>
      )}
    </>
  )
}

function Attachment({ a, onOpenImage }: { a: ChatAttachment; onOpenImage: (url: string) => void }) {
  if (!a.url) {
    return <div className="cx-file"><FileText size={20} /><span className="cx-ellipsis">{a.name} (unavailable)</span></div>
  }
  if (a.mime.startsWith('image/')) {
    return <img className="cx-image" src={a.url} alt={a.name} loading="lazy" onClick={() => onOpenImage(a.url!)} />
  }
  if (a.mime.startsWith('video/')) {
    return <video className="cx-video" src={a.url} controls preload="metadata" />
  }
  if (a.mime.startsWith('audio/')) {
    return <audio src={a.url} controls preload="metadata" style={{ maxWidth: 300 }} />
  }
  return (
    <a className="cx-file" href={a.url} target="_blank" rel="noopener noreferrer" download={a.name}>
      <FileText size={22} color="var(--color-primary)" />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="cx-ellipsis font-medium" style={{ fontSize: 13 }}>{a.name}</div>
        <div className="text-muted" style={{ fontSize: 11 }}>{formatBytes(a.size)}</div>
      </div>
    </a>
  )
}

const ROLE_COLORS: Record<string, string> = { teacher: '#7B1FA2', admin: '#DB4437', student: '#5C6BC0' }

function MessageItem({
  message: m, meId, isGroupAdmin, continuation,
  onReact, onVote, onClosePoll, onDelete, onOpenImage,
}: Props) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  if (m.kind === 'system') {
    return <div className="cx-system">{m.body}</div>
  }

  const mine = m.sender?.id === meId
  const time = format(new Date(m.created_at), 'h:mm a')
  const myReaction = Object.entries(m.reactions).find(([, ids]) => ids.includes(meId))?.[0] || null
  const canDelete = !m.deleted && (mine || isGroupAdmin)
  const role = m.sender?.role || 'student'

  return (
    <div className={`cx-row ${mine ? 'mine' : ''} ${continuation ? 'cont' : ''} ${pickerOpen ? 'picking' : ''}`}>
      {!mine && (continuation
        ? <div className="cx-avatar-spacer" />
        : <div className="cx-avatar-sm" style={{ background: ROLE_COLORS[role] || '#5C6BC0' }} title={m.sender?.full_name}>
            {initials(m.sender?.full_name)}
          </div>)}

      <div className="cx-bubble-wrap" ref={wrapRef}>
        {!m.deleted && (
          <div className="cx-actions">
            <button aria-label="React" onClick={() => setPickerOpen(o => !o)}><SmilePlus size={16} /></button>
            {canDelete && <button aria-label="Delete" onClick={() => onDelete(m)}><Trash2 size={15} /></button>}
          </div>
        )}
        {pickerOpen && wrapRef.current && (
          <ReactionPicker
            anchor={wrapRef.current}
            alignRight={mine}
            current={myReaction}
            onPick={e => { onReact(m, myReaction === e ? null : e); setPickerOpen(false) }}
            onClose={() => setPickerOpen(false)}
          />
        )}

        <div className={`cx-bubble ${m.is_important ? 'important' : ''} ${m.deleted ? 'deleted' : ''}`}>
          {!mine && !continuation && m.sender && (
            <div className="cx-sender" style={{ color: ROLE_COLORS[role] || 'inherit' }}>
              {m.sender.full_name}
              {role !== 'student' && <span className="badge badge-purple" style={{ fontSize: 10, padding: '0 6px', textTransform: 'capitalize' }}>{role}</span>}
            </div>
          )}

          {m.deleted ? (
            <span>🚫 This message was deleted</span>
          ) : (
            <>
              {m.is_important && <div className="cx-important-tag"><AlertCircle size={13} /> IMPORTANT</div>}

              {m.attachments.length > 0 && (
                <div className="cx-attachments">
                  {m.attachments.map((a, i) => <Attachment key={i} a={a} onOpenImage={onOpenImage} />)}
                </div>
              )}

              {m.poll && <Poll message={m} meId={meId} canClose={mine || isGroupAdmin} onVote={onVote} onClose={onClosePoll} />}

              {m.body && <div className="cx-body"><Linkified text={m.body} /></div>}
            </>
          )}
          <div className="cx-meta">{time}</div>
        </div>

        {Object.keys(m.reactions).length > 0 && (
          <div className="cx-reactions">
            {Object.entries(m.reactions).map(([emoji, ids]) => (
              <button
                key={emoji}
                className={`cx-reaction ${ids.includes(meId) ? 'mine' : ''}`}
                onClick={() => onReact(m, ids.includes(meId) ? null : emoji)}
              >
                {emoji}<span>{ids.length}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Emoji picker rendered in a fixed-position portal so the chat pane's scroll
 * container can never clip it. Opens above the bubble (below when there is no
 * room), aligned to the bubble's inner edge and clamped to the viewport.
 */
function ReactionPicker({ anchor, alignRight, current, onPick, onClose }: {
  anchor: HTMLElement; alignRight: boolean; current: string | null
  onPick: (emoji: string) => void; onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const a = anchor.getBoundingClientRect()
    const w = el.offsetWidth
    const h = el.offsetHeight
    const margin = 8
    let top = a.top - h - 6
    if (top < margin + 64) top = a.bottom + 6 // no room above (under the top bar)
    let left = alignRight ? a.right - w : a.left
    left = Math.max(margin, Math.min(left, window.innerWidth - w - margin))
    top = Math.max(margin, Math.min(top, window.innerHeight - h - margin))
    setPos({ top, left })
  }, [anchor, alignRight])

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node) || anchor.contains(e.target as Node)) return
      onClose()
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const onScroll = (e: Event) => { if (!ref.current?.contains(e.target as Node)) onClose() }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onClose)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onClose)
    }
  }, [anchor, onClose])

  return createPortal(
    <div
      ref={ref}
      className="cx-picker"
      role="menu"
      style={pos ? { top: pos.top, left: pos.left } : { top: -9999, left: -9999 }}
    >
      {QUICK_REACTIONS.map(e => (
        <button key={e} aria-label={`React ${e}`} className={current === e ? 'active' : ''} onClick={() => onPick(e)}>{e}</button>
      ))}
    </div>,
    document.body,
  )
}

function Poll({ message: m, meId, canClose, onVote, onClose }: {
  message: ChatMessage; meId: string; canClose: boolean
  onVote: (m: ChatMessage, ids: string[]) => void; onClose: (m: ChatMessage) => void
}) {
  const poll = m.poll!
  const mine = poll.options.filter(o => o.voter_ids.includes(meId)).map(o => o.id)
  const voters = new Set(poll.options.flatMap(o => o.voter_ids))
  const total = voters.size

  const toggle = (id: string) => {
    if (poll.closed) return
    if (poll.allow_multiple) {
      onVote(m, mine.includes(id) ? mine.filter(x => x !== id) : [...mine, id])
    } else {
      onVote(m, mine.includes(id) ? [] : [id])
    }
  }

  return (
    <div className="cx-poll">
      <div className="cx-poll-q"><BarChart3 size={16} style={{ marginTop: 3, flexShrink: 0 }} color="var(--color-primary)" />{poll.question}</div>
      <div className="text-muted" style={{ fontSize: 11, marginBottom: 6 }}>
        {poll.closed ? <><Lock size={11} className="cx-inline-icon" /> Poll closed</> : poll.allow_multiple ? 'Select one or more' : 'Select one'}
      </div>
      {poll.options.map(o => {
        const pct = total ? Math.round((o.voter_ids.length / total) * 100) : 0
        const chosen = mine.includes(o.id)
        return (
          <button key={o.id} className={`cx-poll-opt ${chosen ? 'chosen' : ''}`} disabled={poll.closed} onClick={() => toggle(o.id)}>
            <div className="cx-poll-bar" style={{ width: `${pct}%` }} />
            <input type={poll.allow_multiple ? 'checkbox' : 'radio'} checked={chosen} readOnly tabIndex={-1} disabled={poll.closed} />
            <span style={{ flex: 1 }}>{o.text}</span>
            <span className="text-muted" style={{ fontSize: 12, fontWeight: 600 }}>{o.voter_ids.length} · {pct}%</span>
          </button>
        )
      })}
      <div className="flex-between" style={{ fontSize: 12 }}>
        <span className="text-muted">{total} {total === 1 ? 'vote' : 'votes'}</span>
        {canClose && !poll.closed && (
          <button className="btn btn-ghost btn-sm" style={{ padding: '2px 8px', fontSize: 12 }} onClick={() => onClose(m)}>Close poll</button>
        )}
      </div>
    </div>
  )
}

export default memo(MessageItem)
