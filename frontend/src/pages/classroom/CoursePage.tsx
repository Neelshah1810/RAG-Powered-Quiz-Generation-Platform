// ============================================================
// Academix AI — Course Page
// Google Classroom parity: Stream / Classwork / People tabs
// Multi-file Drag & Drop Uploads + Course-wide Material Re-indexing
// ============================================================
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/lib/api'
import type { Course, StreamItem, Material, Assignment, Enrollment } from '@/lib/types'
import {
  ArrowLeft, Upload, Plus, FileText, ClipboardList, Clock, Download, RefreshCw, X, CheckCircle2, AlertCircle
} from 'lucide-react'
import { format } from 'date-fns'
import toast from 'react-hot-toast'

type Tab = 'stream' | 'classwork' | 'people'

interface BatchFileItem {
  file: File
  title: string
  sourceType: string
  examType: string
  year: string
  status: 'idle' | 'uploading' | 'done' | 'error'
}

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
  const [reindexingAll, setReindexingAll] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [showUpload, setShowUpload] = useState(false)
  const [showAssignment, setShowAssignment] = useState(false)
  const [showAnnounce, setShowAnnounce] = useState(false)

  const [announceText, setAnnounceText] = useState('')
  const [assignTitle, setAssignTitle] = useState('')
  const [assignInstructions, setAssignInstructions] = useState('')
  const [assignDue, setAssignDue] = useState('')
  const [assignPoints, setAssignPoints] = useState(100)

  // Drag and drop / Batch Upload states
  const [selectedFiles, setSelectedFiles] = useState<BatchFileItem[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const [batchUploading, setBatchUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

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

  const needsPoll = materials.some(m =>
    m.ingestion_status === 'pending' || m.ingestion_status === 'processing'
  ) || Object.keys(reindexingIds).length > 0 || reindexingAll

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
          setReindexingAll(false)
          const failed = list.filter(m => m.ingestion_status === 'failed')
          if (failed.length) {
            toast.error(`${failed.length} material(s) failed to index`)
          } else {
            toast.success('All materials indexed cleanly! ✅')
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

  const handleFilesAdded = (files: FileList | File[]) => {
    const arr = Array.from(files)
    if (arr.length === 0) return
    const newItems: BatchFileItem[] = arr.map(f => ({
      file: f,
      title: f.name.replace(/\.[^/.]+$/, '').replace(/[-_]/g, ' '),
      sourceType: 'notes',
      examType: 'internal',
      year: String(new Date().getFullYear()),
      status: 'idle',
    }))
    setSelectedFiles(prev => [...prev, ...newItems])
  }

  const removeFileFromQueue = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index))
  }

  const updateQueueItem = (index: number, field: keyof BatchFileItem, value: any) => {
    setSelectedFiles(prev =>
      prev.map((item, i) => (i === index ? { ...item, [field]: value } : item))
    )
  }

  const uploadBatchMaterials = async () => {
    if (selectedFiles.length === 0) return
    setBatchUploading(true)
    let successCount = 0

    for (let i = 0; i < selectedFiles.length; i++) {
      const item = selectedFiles[i]
      if (item.status === 'done') continue

      setSelectedFiles(prev =>
        prev.map((f, idx) => (idx === i ? { ...f, status: 'uploading' } : f))
      )

      const form = new FormData()
      form.append('file', item.file)
      form.append('title', item.title || item.file.name)
      form.append('source_type', item.sourceType)
      if (item.sourceType === 'pyq') {
        form.append('exam_type', item.examType)
        if (item.year) form.append('year', item.year)
      }

      try {
        await api.post(`/classroom/${courseId}/materials`, form, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        setSelectedFiles(prev =>
          prev.map((f, idx) => (idx === i ? { ...f, status: 'done' } : f))
        )
        successCount++
      } catch (err: any) {
        setSelectedFiles(prev =>
          prev.map((f, idx) => (idx === i ? { ...f, status: 'error' } : f))
        )
        toast.error(`Failed to upload ${item.file.name}: ${err.response?.data?.detail || 'Error'}`)
      }
    }

    setBatchUploading(false)
    if (successCount > 0) {
      toast.success(`Successfully uploaded ${successCount} file(s) for RAG indexing`)
      await refreshMaterials()
      setShowUpload(false)
      setSelectedFiles([])
    }
  }

  const reindexAllMaterials = async () => {
    if (!courseId) return
    setReindexingAll(true)
    setMaterials(prev => prev.map(m => ({ ...m, ingestion_status: 'processing' })))
    try {
      await api.post(`/rag/courses/${courseId}/reindex-all`)
      toast.success('Started full re-indexing of all course materials!')
      await refreshMaterials()
    } catch (err: any) {
      setReindexingAll(false)
      toast.error(err.response?.data?.detail || 'Re-indexing failed')
      await refreshMaterials()
    }
  }

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
    m.ingestion_status === 'pending' || m.ingestion_status === 'processing' || reindexingIds[m.id] || reindexingAll
  ).length

  if (loading) return <div className="skeleton" style={{ height: 400, borderRadius: 12 }} />

  return (
    <div>
      {/* Banner */}
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
              <div className="avatar">
                {item.author_name ? item.author_name.trim().charAt(0).toUpperCase() : (user?.full_name ? user.full_name.trim().charAt(0).toUpperCase() : 'U')}
              </div>
              <div style={{ flex: 1 }}>
                <div className="flex-between">
                  <span className="font-medium">{item.author_name || user?.full_name || 'User'}</span>
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
        <div style={{ maxWidth: 780, margin: '0 auto' }}>
          {isTeacher && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
              <button className="btn btn-primary" onClick={() => setShowAssignment(true)}>
                <Plus size={16} /> Assignment
              </button>
              <button className="btn btn-secondary" onClick={() => setShowUpload(true)}>
                <Upload size={16} /> Upload Material (Multi / Drag & Drop)
              </button>
              <button
                className="btn btn-secondary"
                onClick={reindexAllMaterials}
                disabled={reindexingAll || materials.length === 0}
                title="Re-index all course materials for RAG vector search"
              >
                <RefreshCw size={16} className={reindexingAll ? 'spin' : ''} /> Re-index All Course Material
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

          <h3 style={{ margin: '24px 0 12px' }}>Course Material & RAG Corpus</h3>
          {materials.length === 0 && (
            <p className="text-muted" style={{ marginBottom: 16 }}>No materials uploaded yet</p>
          )}
          {materials.map(m => {
            const busy = Boolean(reindexingIds[m.id])
              || m.ingestion_status === 'pending'
              || m.ingestion_status === 'processing'
              || reindexingAll
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
                        title="Re-index file for RAG"
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
              <div className="avatar">
                {p.user_name ? p.user_name.trim().charAt(0).toUpperCase() : (p.user_email ? p.user_email.trim().charAt(0).toUpperCase() : 'T')}
              </div>
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
              <div className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>
                {p.user_name ? p.user_name.trim().charAt(0).toUpperCase() : (p.user_email ? p.user_email.trim().charAt(0).toUpperCase() : 'S')}
              </div>
              <div>
                <div className="font-medium">{p.user_name}</div>
                <div className="text-muted text-small">{p.user_email}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Multi-File Upload & Drag-and-Drop Modal */}
      {showUpload && (
        <div className="modal-overlay" onClick={() => setShowUpload(false)}>
          <div
            className="modal"
            style={{ maxWidth: 700, width: '90%' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="modal-header">
              <h3>Upload Course Materials (Multi-File / Drag & Drop)</h3>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowUpload(false)}>
                <X size={18} />
              </button>
            </div>

            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* Drag and Drop Zone */}
              <div
                style={{
                  border: `2px dashed ${isDragOver ? '#4285F4' : 'var(--color-border)'}`,
                  borderRadius: 12,
                  padding: '30px 20px',
                  textAlign: 'center',
                  background: isDragOver ? '#E8F0FE' : 'var(--color-surface-2)',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                }}
                onDragOver={e => {
                  e.preventDefault()
                  setIsDragOver(true)
                }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={e => {
                  e.preventDefault()
                  setIsDragOver(false)
                  if (e.dataTransfer.files) {
                    handleFilesAdded(e.dataTransfer.files)
                  }
                }}
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload size={36} color="#4285F4" style={{ marginBottom: 8 }} />
                <p className="font-medium">Drag & Drop multiple files here, or click to browse</p>
                <p className="text-muted text-small" style={{ marginTop: 4 }}>
                  Supports any document, text file, code file, PDF, DOCX, PPTX, CSV, JSON, LOG, etc.
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  style={{ display: 'none' }}
                  onChange={e => {
                    if (e.target.files) handleFilesAdded(e.target.files)
                  }}
                />
              </div>

              {/* Queue List */}
              {selectedFiles.length > 0 && (
                <div>
                  <h4 style={{ marginBottom: 10 }}>Selected Files ({selectedFiles.length})</h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 260, overflowY: 'auto' }}>
                    {selectedFiles.map((item, idx) => (
                      <div
                        key={idx}
                        style={{
                          padding: 12,
                          borderRadius: 8,
                          border: '1px solid var(--color-border)',
                          background: 'var(--color-surface)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: 8,
                        }}
                      >
                        <div className="flex-between">
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                            <FileText size={18} color="#4285F4" />
                            <span className="font-medium text-small text-ellipsis" title={item.file.name}>
                              {item.file.name} ({(item.file.size / 1024).toFixed(1)} KB)
                            </span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            {item.status === 'done' && <CheckCircle2 size={16} color="#0F9D58" />}
                            {item.status === 'uploading' && <RefreshCw size={16} className="spin" color="#4285F4" />}
                            {item.status === 'error' && <AlertCircle size={16} color="#DB4437" />}
                            <button
                              className="btn btn-ghost btn-icon text-small"
                              onClick={() => removeFileFromQueue(idx)}
                              disabled={batchUploading}
                            >
                              <X size={14} />
                            </button>
                          </div>
                        </div>

                        <div className="grid-3" style={{ gap: 8 }}>
                          <input
                            className="input"
                            style={{ fontSize: 12, padding: '4px 8px' }}
                            placeholder="Title"
                            value={item.title}
                            onChange={e => updateQueueItem(idx, 'title', e.target.value)}
                          />

                          <select
                            className="input"
                            style={{ fontSize: 12, padding: '4px 8px' }}
                            value={item.sourceType}
                            onChange={e => updateQueueItem(idx, 'sourceType', e.target.value)}
                          >
                            <option value="notes">Notes</option>
                            <option value="textbook">Textbook</option>
                            <option value="pyq">PYQ</option>
                          </select>

                          {item.sourceType === 'pyq' ? (
                            <select
                              className="input"
                              style={{ fontSize: 12, padding: '4px 8px' }}
                              value={item.examType}
                              onChange={e => updateQueueItem(idx, 'examType', e.target.value)}
                            >
                              <option value="internal">Internal</option>
                              <option value="external">External</option>
                            </select>
                          ) : (
                            <div className="text-muted text-small" style={{ display: 'flex', alignItems: 'center' }}>
                              Auto RAG Index
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowUpload(false)} disabled={batchUploading}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={uploadBatchMaterials}
                disabled={selectedFiles.length === 0 || batchUploading}
              >
                {batchUploading ? 'Uploading & Indexing...' : `Upload & Index ${selectedFiles.length} File(s)`}
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
