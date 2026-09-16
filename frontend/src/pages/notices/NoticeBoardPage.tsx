// ============================================================
// Academix AI — Notice Board Page
// Filterable notification feed visible to all roles
// ============================================================
import { useState, useEffect } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/lib/api'
import type { Course, Notice } from '@/lib/types'
import { Bell, ClipboardList, Calendar, Award, AlertCircle } from 'lucide-react'
import { format } from 'date-fns'
import toast from 'react-hot-toast'

const typeIcons: Record<string, any> = {
  announcement: Bell,
  assignment: ClipboardList,
  grade: Award,
  event: Calendar,
  admin: AlertCircle,
}

const typeColors: Record<string, string> = {
  announcement: '#4285F4',
  assignment: '#F4B400',
  grade: '#0F9D58',
  event: '#DB4437',
  admin: '#AB47BC',
}

export default function NoticeBoardPage() {
  const { user } = useAuth()
  const [notices, setNotices] = useState<Notice[]>([])
  const [courses, setCourses] = useState<Course[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [filter, setFilter] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [formTitle, setFormTitle] = useState('')
  const [formBody, setFormBody] = useState('')
  const [formType, setFormType] = useState('announcement')
  const [formCourseId, setFormCourseId] = useState('')

  const canPost = user?.role === 'teacher' || user?.role === 'admin'
  const isAdmin = user?.role === 'admin'

  useEffect(() => { loadNotices() }, [filter])
  useEffect(() => {
    if (canPost) {
      api.get('/courses/').then(r => setCourses(r.data || [])).catch(() => {})
    }
  }, [canPost])

  const loadNotices = async () => {
    setLoading(true)
    try {
      const params: any = {}
      if (filter) params.notice_type = filter
      const { data } = await api.get('/notices/', { params })
      setNotices(data.notices || [])
      setUnreadCount(data.unread_count || 0)
    } catch { /* ignore */ }
    setLoading(false)
  }

  const markAllRead = async () => {
    const unread = notices.filter(n => !n.is_read).map(n => n.id)
    if (unread.length === 0) return
    try {
      await api.post('/notices/mark-read', { notice_ids: unread })
      loadNotices()
      toast.success('All marked as read')
    } catch { /* ignore */ }
  }

  const createNotice = async () => {
    if (!formTitle || !formBody) { toast.error('Fill in title and body'); return }
    if (!isAdmin && !formCourseId) {
      toast.error('Select a course to post to')
      return
    }
    try {
      await api.post('/notices/', {
        title: formTitle,
        body: formBody,
        notice_type: formType,
        course_id: formCourseId || null,
      })
      toast.success('Notice posted')
      setShowCreate(false); setFormTitle(''); setFormBody(''); setFormType('announcement'); setFormCourseId('')
      loadNotices()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to post notice')
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">Notice Board</h1>
          {unreadCount > 0 && <span className="badge badge-blue" style={{ marginLeft: 8 }}>{unreadCount} unread</span>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {unreadCount > 0 && (
            <button className="btn btn-ghost" onClick={markAllRead}>Mark all read</button>
          )}
          {canPost && (
            <button className="btn btn-primary" onClick={() => setShowCreate(true)}>Post Notice</button>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 20, flexWrap: 'wrap' }}>
        {['', 'announcement', 'assignment', 'grade', 'event', 'admin'].map(f => (
          <button key={f} className={`badge ${filter === f ? 'badge-blue' : 'badge-gray'}`}
            style={{ cursor: 'pointer', padding: '5px 14px' }}
            onClick={() => setFilter(f)}>
            {f || 'All'}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[1, 2, 3, 4].map(i => <div key={i} className="skeleton" style={{ height: 80 }} />)}
        </div>
      ) : notices.length === 0 ? (
        <div className="card flex-center" style={{ padding: 60, flexDirection: 'column', gap: 12 }}>
          <Bell size={48} color="var(--color-text-3)" />
          <p className="text-muted">No notices yet</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {notices.map(notice => {
            const Icon = typeIcons[notice.notice_type] || Bell
            const color = typeColors[notice.notice_type] || '#9E9E9E'
            return (
              <div key={notice.id} className={`notice-card ${!notice.is_read ? 'unread' : ''}`}
                style={{ borderLeftColor: !notice.is_read ? color : 'transparent' }}
                onClick={async () => {
                  if (!notice.is_read) {
                    await api.post('/notices/mark-read', { notice_ids: [notice.id] })
                    loadNotices()
                  }
                }}>
                <div style={{
                  width: 40, height: 40, borderRadius: 10,
                  background: color + '15', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                }}>
                  <Icon size={20} color={color} />
                </div>
                <div style={{ flex: 1 }}>
                  <div className="flex-between">
                    <span className="font-medium">{notice.title}</span>
                    <span className="text-muted text-small">
                      {notice.created_at ? format(new Date(notice.created_at), 'MMM d, h:mm a') : ''}
                    </span>
                  </div>
                  <p className="text-muted" style={{ marginTop: 2, fontSize: 13 }}>{notice.body}</p>
                  <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                    {notice.author_name && <span className="badge badge-gray">By: {notice.author_name}</span>}
                    {notice.course_name && <span className="badge badge-gray">{notice.course_name}</span>}
                    <span className="badge badge-gray" style={{ textTransform: 'capitalize' }}>{notice.notice_type}</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Post Notice</h3>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowCreate(false)}>✕</button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="input-group">
                <label className="input-label">
                  {isAdmin ? 'Course (optional — leave blank for institute-wide)' : 'Course'}
                </label>
                <select className="input" value={formCourseId} onChange={e => setFormCourseId(e.target.value)}>
                  <option value="">{isAdmin ? 'Institute-wide' : 'Select a course...'}</option>
                  {courses.map(c => (
                    <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                  ))}
                </select>
              </div>
              <div className="input-group">
                <label className="input-label">Title</label>
                <input className="input" value={formTitle} onChange={e => setFormTitle(e.target.value)} />
              </div>
              <div className="input-group">
                <label className="input-label">Body</label>
                <textarea className="input" value={formBody} onChange={e => setFormBody(e.target.value)} rows={3} />
              </div>
              <div className="input-group">
                <label className="input-label">Type</label>
                <select className="input" value={formType} onChange={e => setFormType(e.target.value)}>
                  <option value="announcement">Announcement</option>
                  <option value="event">Event</option>
                  {isAdmin && <option value="admin">Admin Notice</option>}
                </select>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={createNotice}>Post</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
