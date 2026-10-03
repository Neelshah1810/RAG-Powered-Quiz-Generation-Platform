// ============================================================
// Academix AI — Member picker (scoped directory search)
// Teachers see only people in courses of the semester(s) they teach;
// admins see everyone. Scope is enforced server-side as well.
// ============================================================
import { useEffect, useMemo, useState } from 'react'
import { Search, Users, X } from 'lucide-react'
import api from '@/lib/api'
import { initials } from '@/lib/chat'
import type { DirectoryUser, ScopeCourse } from '@/lib/chat'

interface Props {
  selected: string[]
  onChange: (ids: string[]) => void
  /** Already in the group — shown but not selectable. */
  excludeIds?: string[]
}

export default function MemberPicker({ selected, onChange, excludeIds = [] }: Props) {
  const [q, setQ] = useState('')
  const [courseId, setCourseId] = useState('')
  const [courses, setCourses] = useState<ScopeCourse[]>([])
  const [people, setPeople] = useState<DirectoryUser[]>([])
  const [known, setKnown] = useState<Record<string, DirectoryUser>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/chat/directory/courses').then(r => setCourses(Array.isArray(r.data) ? r.data : [])).catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
    const t = setTimeout(() => {
      api.get('/chat/directory', { params: { q: q || undefined, course_id: courseId || undefined } })
        .then(r => {
          const list: DirectoryUser[] = Array.isArray(r.data) ? r.data : []
          setPeople(list)
          setKnown(k => ({ ...k, ...Object.fromEntries(list.map(u => [u.id, u])) }))
        })
        .catch(() => setPeople([]))
        .finally(() => setLoading(false))
    }, 250)
    return () => clearTimeout(t)
  }, [q, courseId])

  const excluded = useMemo(() => new Set(excludeIds), [excludeIds])
  const selectable = people.filter(p => !excluded.has(p.id))
  const allSelected = selectable.length > 0 && selectable.every(p => selected.includes(p.id))

  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])

  const toggleAll = () => {
    const ids = selectable.map(p => p.id)
    onChange(allSelected ? selected.filter(id => !ids.includes(id)) : Array.from(new Set([...selected, ...ids])))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: 180 }}>
          <Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-3)' }} />
          <input className="input" placeholder="Search by name or email" value={q} onChange={e => setQ(e.target.value)} style={{ paddingLeft: 36 }} />
        </div>
        <select className="input" value={courseId} onChange={e => setCourseId(e.target.value)} style={{ width: 210 }}>
          <option value="">All my semesters</option>
          {courses.map(c => (
            <option key={c.id} value={c.id}>{c.code} · {c.name}{c.semester ? ` (Sem ${c.semester})` : ''}</option>
          ))}
        </select>
      </div>

      {selected.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {selected.map(id => (
            <span key={id} className="cx-chip">
              {known[id]?.full_name || 'Selected user'}
              <button type="button" style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 0, display: 'flex' }} onClick={() => toggle(id)}>
                <X size={13} />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex-between" style={{ fontSize: 13 }}>
        <span className="text-muted">{loading ? 'Searching…' : `${selectable.length} ${selectable.length === 1 ? 'person' : 'people'}`}</span>
        {selectable.length > 0 && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={toggleAll}>
            <Users size={14} /> {allSelected ? 'Unselect all' : courseId ? 'Add whole course' : 'Select all'}
          </button>
        )}
      </div>

      <div className="cx-picker-list">
        {!loading && people.length === 0 && (
          <div className="text-muted" style={{ padding: 16, fontSize: 13, textAlign: 'center' }}>
            No one found. You can add people enrolled in courses of the semester(s) you teach.
          </div>
        )}
        {people.map(p => {
          const inGroup = excluded.has(p.id)
          return (
            <label key={p.id} className={`cx-picker-item ${inGroup ? 'disabled' : ''}`}>
              <input type="checkbox" disabled={inGroup} checked={inGroup || selected.includes(p.id)} onChange={() => toggle(p.id)} />
              <div className="cx-avatar-sm" style={{ background: p.role === 'student' ? '#5C6BC0' : '#7B1FA2' }}>{initials(p.full_name)}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="font-medium cx-ellipsis" style={{ fontSize: 14 }}>{p.full_name}</div>
                <div className="text-muted cx-ellipsis" style={{ fontSize: 12 }}>
                  {p.email}{p.courses.length ? ` · ${p.courses.join(', ')}` : ''}
                </div>
              </div>
              <span className={`badge ${p.role === 'student' ? 'badge-blue' : 'badge-purple'}`} style={{ textTransform: 'capitalize' }}>
                {inGroup ? 'In group' : p.role}
              </span>
            </label>
          )
        })}
      </div>
    </div>
  )
}
