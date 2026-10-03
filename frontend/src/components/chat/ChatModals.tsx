// ============================================================
// Academix AI — Chat modals: create group, add members, create poll
// ============================================================
import { useEffect, useState } from 'react'
import { Megaphone, MessagesSquare, Plus, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'
import MemberPicker from './MemberPicker'
import { errorDetail } from '@/lib/chat'
import type { ChatGroupDetail, PostPolicy } from '@/lib/chat'
import type { Course } from '@/lib/types'


export function PolicyPicker({ value, onChange }: { value: PostPolicy; onChange: (v: PostPolicy) => void }) {
  return (
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
      <label className={`cx-policy-option ${value === 'admins' ? 'selected' : ''}`}>
        <input type="radio" checked={value === 'admins'} onChange={() => onChange('admins')} />
        <div>
          <div className="font-medium" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Megaphone size={15} /> Teachers/admins only</div>
          <div className="text-muted" style={{ fontSize: 12, marginTop: 2 }}>Announcement channel. Students can read, react and vote in polls.</div>
        </div>
      </label>
      <label className={`cx-policy-option ${value === 'everyone' ? 'selected' : ''}`}>
        <input type="radio" checked={value === 'everyone'} onChange={() => onChange('everyone')} />
        <div>
          <div className="font-medium" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><MessagesSquare size={15} /> Everyone can send</div>
          <div className="text-muted" style={{ fontSize: 12, marginTop: 2 }}>Discussion group. Students can also message and share files.</div>
        </div>
      </label>
    </div>
  )
}

export function CreateGroupModal({ onClose, onCreated }: { onClose: () => void; onCreated: (g: ChatGroupDetail) => void }) {
  const { user } = useAuth()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [courseId, setCourseId] = useState('')
  const [policy, setPolicy] = useState<PostPolicy>('admins')
  const [members, setMembers] = useState<string[]>([])
  const [courses, setCourses] = useState<Course[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('/courses/').then(r => {
      const list = Array.isArray(r.data) ? r.data : []
      // A group can only be linked to a course you teach (admins: any).
      setCourses(user?.role === 'admin' ? list : list.filter((c: any) => c.my_role === 'teacher'))
    }).catch(() => {})
  }, [user?.role])

  const submit = async () => {
    if (!name.trim()) { toast.error('Give the group a name'); return }
    setSaving(true)
    try {
      const { data } = await api.post('/chat/groups', {
        name: name.trim(),
        description: description.trim() || null,
        course_id: courseId || null,
        post_policy: policy,
        member_ids: members,
      })
      toast.success('Group created')
      onCreated(data)
    } catch (err: any) {
      if ((err?.response?.status ?? 500) < 500 && err?.response?.status !== 403) toast.error(errorDetail(err, 'Could not create group'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 680 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>New chat group</h3>
          <button className="btn btn-ghost btn-icon" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="input-group">
            <label className="input-label">Group name *</label>
            <input className="input" value={name} maxLength={80} onChange={e => setName(e.target.value)} placeholder="e.g. Sem 5 · Big Data Announcements" autoFocus />
          </div>
          <div className="grid-2" style={{ gap: 12 }}>
            <div className="input-group">
              <label className="input-label">Description</label>
              <input className="input" value={description} maxLength={500} onChange={e => setDescription(e.target.value)} placeholder="Optional" />
            </div>
            <div className="input-group">
              <label className="input-label">Link to course</label>
              <select className="input" value={courseId} onChange={e => setCourseId(e.target.value)}>
                <option value="">None</option>
                {courses.map(c => <option key={c.id} value={c.id}>{c.code} · {c.name}</option>)}
              </select>
            </div>
          </div>
          <div className="input-group">
            <label className="input-label">Who can send messages?</label>
            <PolicyPicker value={policy} onChange={setPolicy} />
          </div>
          <div className="input-group">
            <label className="input-label">Add members ({members.length} selected)</label>
            <MemberPicker selected={members} onChange={setMembers} />
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving || !name.trim()}>
            {saving ? 'Creating…' : 'Create group'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function AddMembersModal({ group, onClose, onDone }: { group: ChatGroupDetail; onClose: () => void; onDone: (g: ChatGroupDetail) => void }) {
  const [selected, setSelected] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    setSaving(true)
    try {
      const { data } = await api.post(`/chat/groups/${group.id}/members`, { user_ids: selected })
      toast.success(`Added ${selected.length} ${selected.length === 1 ? 'member' : 'members'}`)
      onDone(data)
    } catch (err: any) {
      if ((err?.response?.status ?? 500) < 500 && err?.response?.status !== 403) toast.error(errorDetail(err, 'Could not add members'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 640 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Add members to {group.name}</h3>
          <button className="btn btn-ghost btn-icon" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="modal-body">
          <MemberPicker selected={selected} onChange={setSelected} excludeIds={group.members.map(m => m.user_id)} />
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving || selected.length === 0}>
            {saving ? 'Adding…' : `Add ${selected.length || ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}

export function PollModal({ onClose, onSubmit }: {
  onClose: () => void
  onSubmit: (poll: { question: string; options: string[]; allow_multiple: boolean }) => Promise<boolean>
}) {
  const [question, setQuestion] = useState('')
  const [options, setOptions] = useState(['', ''])
  const [multiple, setMultiple] = useState(false)
  const [saving, setSaving] = useState(false)
  const filled = options.map(o => o.trim()).filter(Boolean)
  const valid = question.trim() && filled.length >= 2

  const submit = async () => {
    if (!valid) return
    setSaving(true)
    const ok = await onSubmit({ question: question.trim(), options: filled, allow_multiple: multiple })
    setSaving(false)
    if (ok) onClose()
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 480 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Create poll</h3>
          <button className="btn btn-ghost btn-icon" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="input-group">
            <label className="input-label">Question</label>
            <input className="input" value={question} maxLength={300} onChange={e => setQuestion(e.target.value)} placeholder="Ask a question" autoFocus />
          </div>
          <label className="input-label">Options</label>
          {options.map((o, i) => (
            <div key={i} style={{ display: 'flex', gap: 8 }}>
              <input className="input" value={o} maxLength={150} placeholder={`Option ${i + 1}`}
                onChange={e => setOptions(opts => opts.map((x, j) => j === i ? e.target.value : x))} />
              {options.length > 2 && (
                <button className="btn btn-ghost btn-icon" onClick={() => setOptions(opts => opts.filter((_, j) => j !== i))}><Trash2 size={16} /></button>
              )}
            </div>
          ))}
          {options.length < 12 && (
            <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => setOptions(o => [...o, ''])}>
              <Plus size={14} /> Add option
            </button>
          )}
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
            <input type="checkbox" checked={multiple} onChange={e => setMultiple(e.target.checked)} /> Allow multiple answers
          </label>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={!valid || saving}>{saving ? 'Sending…' : 'Send poll'}</button>
        </div>
      </div>
    </div>
  )
}

