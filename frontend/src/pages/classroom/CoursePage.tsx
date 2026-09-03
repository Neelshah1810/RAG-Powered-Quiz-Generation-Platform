// ============================================================
// Academix AI — Course Page
// Google Classroom parity: Stream / Classwork / People tabs
// ============================================================
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/lib/api'
import type { Course, StreamItem, Material, Assignment, Enrollment } from '@/lib/types'
import { ArrowLeft, Upload, Plus, FileText, ClipboardList, Clock, Download, RefreshCw } from 'lucide-react'
import { format } from 'date-fns'
import toast from 'react-hot-toast'

type Tab = 'stream' | 'classwork' | 'people'

function statusBadgeClass(status?: string) {
  if (status === 'indexed') return 'badge-green'
  if (status === 'failed') return 'badge-red'
  if (status === 'processing' || status === 'pending') return 'badge-yellow'
  return 'badge-gray'
}

function statusLabel(m: Material) {
  const status = m.ingestion_status || 'not_indexed'
  if (status === 'indexed') {
    const n = m.chunk_count || 0
    return n ? `indexed · ${n} chunks` : 'indexed'
  }
  if (status === 'processing') return 'indexing…'
  if (status === 'pending') return 'queued'
  if (status === 'failed') return 'failed'
  return status.replace('_', ' ')
}

export default function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [course, setCourse] = useState<Course | null>(null)
  const [tab, setTab] = useState<Tab>('stream')
  const [stream, setStream] = useState<StreamItem[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [people, setPeople] = useState<Enrollment[]>([])
  const [loading, setLoading] = useState(true)
  const [reindexingIds, setReindexingIds] = useState<Record<string, boolean>>({})
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [showUpload, setShowUpload] = useState(false)
  const [showAssignment, setShowAssignment] = useState(false)
  const [showAnnounce, setShowAnnounce] = useState(false)

  const [announceText, setAnnounceText] = useState('')
  const [assignTitle, setAssignTitle] = useState('')
  const [assignInstructions, setAssignInstructions] = useState('')
  const [assignDue, setAssignDue] = useState('')
  const [assignPoints, setAssignPoints] = useState(100)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadTitle, setUploadTitle] = useState('')
  const [uploadSourceType, setUploadSourceType] = useState('notes')
  const [uploadExamType, setUploadExamType] = useState('internal')
  const [uploadYear, setUploadYear] = useState(String(new Date().getFullYear()))

  const refreshMaterials = useCallback(async () => {
    if (!courseId) return [] as Material[]
    const { data } = await api.get(`/classroom/${courseId}/materials`)
    const list = (data || []) as Material[]
    setMaterials(list)
    return list
  }, [courseId])

  useEffect(() => {
    if (!courseId) return
    const load = async () => {
      try {
        const [c, s, m, a, p] = await Promise.all([
          api.get(`/courses/${courseId}`),
          api.get(`/classroom/${courseId}/stream`),
          api.get(`/classroom/${courseId}/materials`),
          api.get(`/classroom/${courseId}/assignments`),
          api.get(`/courses/${courseId}/enrollments`),
        ])
        setCourse(c.data)
        setStream(s.data || [])
        setMaterials(m.data || [])
        setAssignments(a.data || [])
        setPeople(p.data || [])
      } catch { /* ignore */ }
      setLoading(false)
    }
    load()
  }, [courseId])

  // Poll while any material is pending/processing (or local reindex in flight)
  const needsPoll = materials.some(m =>
    m.ingestion_status === 'pending' || m.ingestion_status === 'processing'
  ) || Object.keys(reindexingIds).length > 0

  useEffect(() => {
    if (!needsPoll || !courseId) {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      return
    }

    if (pollRef.current) return

    pollRef.current = setInterval(async () => {
      try {
        const list = await refreshMaterials()
        const stillBusy = list.some(m =>
          m.ingestion_status === 'pending' || m.ingestion_status === 'processing'
        )
        if (!stillBusy) {
          setReindexingIds({})
          const failed = list.filter(m => m.ingestion_status === 'failed')
          if (failed.length) {
            toast.error(`${failed.length} material(s) failed to index`)
          } else {
            toast.success('Material indexing complete')
          }
        }
      } catch { /* keep polling */ }
    }, 2500)

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [needsPoll, courseId, refreshMaterials])

  const postAnnouncement = async () => {
    if (!announceText.trim()) return
    try {
      await api.post(`/classroom/${courseId}/announcements`, {
        course_id: courseId, text: announceText
      })
      toast.success('Announcement posted')
      setAnnounceText('')
      setShowAnnounce(false)
      const s = await api.get(`/classroom/${courseId}/stream`)
      setStream(s.data || [])
    } catch { toast.error('Failed to post') }
  }

  const createAssignment = async () => {
    if (!assignTitle.trim()) return
    try {
      await api.post(`/classroom/${courseId}/assignments`, {
        course_id: courseId,
        title: assignTitle,
        instructions: assignInstructions,
        due_at: assignDue || null,
        max_points: assignPoints,
      })
      toast.success('Assignment created')
      setShowAssignment(false)
      setAssignTitle(''); setAssignInstructions(''); setAssignDue(''); setAssignPoints(100)
      const a = await api.get(`/classroom/${courseId}/assignments`)
      setAssignments(a.data || [])
    } catch { toast.error('Failed to create') }
  }

  const uploadMaterial = async () => {
    if (!uploadFile || !uploadTitle.trim()) return
    if (uploadSourceType === 'pyq' && !uploadExamType) {
      toast.error('Select exam type for PYQ papers')
      return
    }
    const form = new FormData()
    form.append('file', uploadFile)
    form.append('title', uploadTitle)
    form.append('source_type', uploadSourceType)
    if (uploadSourceType === 'pyq') {
      form.append('exam_type', uploadExamType)
      if (uploadYear) form.append('year', uploadYear)
    }
    try {
      await api.post(`/classroom/${courseId}/materials`, form, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      toast.success('Uploaded — indexing for RAG started')
      setShowUpload(false)
      setUploadFile(null); setUploadTitle(''); setUploadSourceType('notes')
      await refreshMaterials()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Upload failed')
    }
  }

  const downloadMaterial = async (materialId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      const { data } = await api.get(`/classroom/${courseId}/materials/${materialId}/download`)
      if (data.download_url) {
        window.open(data.download_url, '_blank')
      } else {
        toast.error(data.error || 'Download not available')
      }
    } catch {
      toast.error('Failed to get download link')
    }
  }

  const reindexMaterial = async (m: Material, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!m.document_id) {
      toast.error('This material has no RAG document yet — re-upload it')
      return
    }
    setReindexingIds(prev => ({ ...prev, [m.id]: true }))
    setMaterials(prev => prev.map(row =>
      row.id === m.id
        ? { ...row, ingestion_status: 'processing', ingestion_error: undefined }
        : row
    ))
    try {
      await api.post(`/rag/documents/${m.document_id}/reindex`)
      toast.success(`Re-indexing “${m.title}”…`)
      await refreshMaterials()
    } catch (err: any) {
      setReindexingIds(prev => {
        const next = { ...prev }
        delete next[m.id]
        return next
      })
      toast.error(err.response?.data?.detail || 'Reindex failed')
      await refreshMaterials()
    }
  }

  const isTeacher = user?.role === 'teacher' || user?.role === 'admin'
  const indexingCount = materials.filter(m =>
    m.ingestion_status === 'pending' || m.ingestion_status === 'processing' || reindexingIds[m.id]
  ).length

  if (loading) return <div className="skeleton" style={{ height: 400, borderRadius: 12 }} />

  return (
    <div>
      <div style={{
        background: course?.banner_color || '#4285F4',
        borderRadius: 12,
        padding: '24px 28px',
        color: 'white',
        marginBottom: 24,
      }}>
        <button className="btn btn-ghost" onClick={() => navigate('/classroom')}
          style={{ color: 'white', marginBottom: 8, padding: '4px 8px' }}>
          <ArrowLeft size={18} /> Back
        </button>
        <h1 style={{ color: 'white', fontSize: 24 }}>{course?.name}</h1>
        <p style={{ opacity: 0.85, marginTop: 4 }}>
          {course?.code} {course?.department_name ? `· ${course.department_name}` : ''}
        </p>
      </div>

      <div className="tabs" style={{ marginBottom: 24 }}>
        {(['stream', 'classwork', 'people'] as Tab[]).map(t => (
          <div key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}
            style={{ textTransform: 'capitalize' }}>{t}</div>
        ))}
      </div>

      {tab === 'stream' && (
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          {isTeacher && (
            <div className="card" style={{ padding: 16, marginBottom: 16 }}>
              {showAnnounce ? (
                <div>
                  <textarea className="input" value={announceText}
                    onChange={e => setAnnounceText(e.target.value)}
                    placeholder="Share something with your class..." rows={3} autoFocus />
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
                    <button className="btn btn-ghost" onClick={() => setShowAnnounce(false)}>Cancel</button>
                    <button className="btn btn-primary" onClick={postAnnouncement}>Post</button>
                  </div>
                </div>
              ) : (
                <div onClick={() => setShowAnnounce(true)} style={{
                  padding: '10px 16px', borderRadius: 24, background: 'var(--color-surface-2)',
                  cursor: 'text', color: 'var(--color-text-3)',
                }}>
                  Announce something to your class...
                </div>
              )}
            </div>
          )}

          {stream.map(item => (
            <div key={item.id} className="stream-item" style={{ marginBottom: 12 }}>
              <div className="avatar">{item.author_name?.charAt(0) || '?'}</div>
              <div style={{ flex: 1 }}>
                <div className="flex-between">
                  <span className="font-medium">{item.author_name}</span>
                  <span className="text-muted text-small">
                    {item.created_at ? format(new Date(item.created_at), 'MMM d, h:mm a') : ''}
                  </span>
                </div>
                {item.type === 'announcement' && <p style={{ marginTop: 6 }}>{item.text}</p>}
                {item.type === 'material' && (
                  <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <FileText size={16} color="var(--color-primary)" />
                    <span>Posted new material: <strong>{item.title}</strong></span>
                  </div>
                )}
                {item.type === 'assignment' && (
                  <div style={{ marginTop: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <ClipboardList size={16} color="var(--color-primary)" />
                      <span>Posted new assignment: <strong>{item.title}</strong></span>
                    </div>
                    {item.due_at && (
                      <span className="text-muted text-small" style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 4 }}>
                        <Clock size={12} /> Due {format(new Date(item.due_at), 'MMM d, h:mm a')}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          {stream.length === 0 && <p className="text-muted" style={{ textAlign: 'center', padding: 40 }}>No activity yet</p>}
        </div>
      )}

      {tab === 'classwork' && (
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          {isTeacher && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
              <button className="btn btn-primary" onClick={() => setShowAssignment(true)}>
                <Plus size={16} /> Assignment
              </button>
              <button className="btn btn-secondary" onClick={() => setShowUpload(true)}>
                <Upload size={16} /> Upload Material
              </button>
              {indexingCount > 0 && (
                <span className="badge badge-yellow" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <RefreshCw size={12} className="spin" />
                  Indexing {indexingCount} file{indexingCount === 1 ? '' : 's'}…
                </span>
              )}
            </div>
          )}

          <h3 style={{ marginBottom: 12 }}>Assignments</h3>
          {assignments.map(a => (
            <div key={a.id} className="card" style={{ padding: 16, marginBottom: 8, cursor: 'pointer' }}
              onClick={() => navigate(`/classroom/${courseId}/assignment/${a.id}`)}>
              <div className="flex-between">
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <ClipboardList size={20} color="var(--color-primary)" />
                  <div>
                    <div className="font-medium">{a.title}</div>
                    <div className="text-muted text-small">
                      {a.due_at ? `Due ${format(new Date(a.due_at), 'MMM d')}` : 'No due date'} · {a.max_points} pts
                    </div>
                  </div>
                </div>
                {isTeacher && (
                  <span className="badge badge-blue">{a.submission_count || 0} submitted</span>
                )}
              </div>
            </div>
          ))}

          <h3 style={{ margin: '24px 0 12px' }}>Materials</h3>
          {materials.length === 0 && (
            <p className="text-muted" style={{ marginBottom: 16 }}>No materials uploaded yet</p>
          )}
          {materials.map(m => {
            const busy = Boolean(reindexingIds[m.id])
              || m.ingestion_status === 'pending'
              || m.ingestion_status === 'processing'
            return (
              <div key={m.id} className="card" style={{ padding: 16, marginBottom: 8 }}>
                <div className="flex-between" style={{ gap: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, flex: 1 }}>
                    <FileText size={20} color="#0F9D58" />
                    <div style={{ minWidth: 0 }}>
                      <div className="font-medium">{m.title}</div>
                      <div className="text-muted text-small" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {m.file_name}
                        {m.source_type ? ` · ${m.source_type}` : ''}
                        {m.source_type === 'pyq' && m.exam_type ? ` (${m.exam_type})` : ''}
                      </div>
                      {m.ingestion_status === 'failed' && m.ingestion_error && (
                        <div className="text-small" style={{ color: 'var(--color-danger)', marginTop: 4 }}>
                          {m.ingestion_error}
                        </div>
                      )}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                    <span
                      className={`badge ${statusBadgeClass(busy && m.ingestion_status !== 'failed' ? 'processing' : m.ingestion_status)}`}
                      title={m.ingestion_error || m.ingestion_status || ''}
                    >
                      {busy && m.ingestion_status !== 'failed' ? 'indexing…' : statusLabel(m)}
                    </span>
                    {isTeacher && m.document_id && (
                      <button
                        className="btn btn-ghost btn-icon"
                        onClick={(e) => reindexMaterial(m, e)}
                        disabled={busy}
                        title="Re-index for RAG"
                      >
                        <RefreshCw size={18} className={busy ? 'spin' : undefined} />
                      </button>
                    )}
                    <button className="btn btn-ghost btn-icon" onClick={(e) => downloadMaterial(m.id, e)} title="Download">
                      <Download size={18} />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {tab === 'people' && (
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          <h3 style={{ marginBottom: 12 }}>Teachers ({people.filter(p => p.role === 'teacher').length})</h3>
          {people.filter(p => p.role === 'teacher').map(p => (
            <div key={p.id} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '10px 0', borderBottom: '1px solid var(--color-border)',
            }}>
              <div className="avatar">{p.user_name?.charAt(0) || '?'}</div>
              <div>
                <div className="font-medium">{p.user_name}</div>
                <div className="text-muted text-small">{p.user_email}</div>
              </div>
            </div>
          ))}
          <h3 style={{ margin: '24px 0 12px' }}>Students ({people.filter(p => p.role === 'student').length})</h3>
          {people.filter(p => p.role === 'student').map(p => (
            <div key={p.id} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '10px 0', borderBottom: '1px solid var(--color-border)',
            }}>
              <div className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>{p.user_name?.charAt(0) || '?'}</div>
              <div>
                <div className="font-medium">{p.user_name}</div>
                <div className="text-muted text-small">{p.user_email}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {showUpload && (
        <div className="modal-overlay" onClick={() => setShowUpload(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Upload Material</h3>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowUpload(false)}>✕</button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="input-group">
                <label className="input-label">Title</label>
                <input className="input" value={uploadTitle} onChange={e => setUploadTitle(e.target.value)}
                  placeholder="e.g. Chapter 3 Notes" />
              </div>
              <div className="input-group">
                <label className="input-label">Type</label>
                <select className="input" value={uploadSourceType} onChange={e => setUploadSourceType(e.target.value)}>
                  <option value="notes">Lecture Notes</option>
                  <option value="textbook">Textbook</option>
                  <option value="pyq">Previous Year Question Paper</option>
                </select>
              </div>
              {uploadSourceType === 'pyq' && (
                <div className="grid-2" style={{ gap: 12 }}>
                  <div className="input-group">
                    <label className="input-label">Exam type</label>
                    <select className="input" value={uploadExamType} onChange={e => setUploadExamType(e.target.value)}>
                      <option value="internal">Internal</option>
                      <option value="external">External</option>
                    </select>
                  </div>
                  <div className="input-group">
                    <label className="input-label">Year</label>
                    <input className="input" type="number" value={uploadYear}
                      onChange={e => setUploadYear(e.target.value)} min={1990} max={2100} />
                  </div>
                </div>
              )}
              <div className="input-group">
                <label className="input-label">File (PDF, DOCX, PPTX, TXT)</label>
                <input type="file" className="input" onChange={e => setUploadFile(e.target.files?.[0] || null)}
                  accept=".pdf,.docx,.pptx,.txt" />
              </div>
              <p className="text-muted text-small">
                Uploaded materials are automatically indexed for AI quiz generation. Status appears next to each file.
              </p>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowUpload(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={uploadMaterial} disabled={!uploadFile || !uploadTitle}>
                Upload
              </button>
            </div>
          </div>
        </div>
      )}

      {showAssignment && (
        <div className="modal-overlay" onClick={() => setShowAssignment(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Assignment</h3>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowAssignment(false)}>✕</button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="input-group">
                <label className="input-label">Title</label>
                <input className="input" value={assignTitle} onChange={e => setAssignTitle(e.target.value)}
                  placeholder="Assignment title" />
              </div>
              <div className="input-group">
                <label className="input-label">Instructions</label>
                <textarea className="input" value={assignInstructions} onChange={e => setAssignInstructions(e.target.value)}
                  placeholder="Assignment instructions..." rows={3} />
              </div>
              <div className="grid-2">
                <div className="input-group">
                  <label className="input-label">Due Date</label>
                  <input className="input" type="datetime-local" value={assignDue} onChange={e => setAssignDue(e.target.value)} />
                </div>
                <div className="input-group">
                  <label className="input-label">Max Points</label>
                  <input className="input" type="number" value={assignPoints} onChange={e => setAssignPoints(Number(e.target.value))} />
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowAssignment(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={createAssignment} disabled={!assignTitle}>
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
