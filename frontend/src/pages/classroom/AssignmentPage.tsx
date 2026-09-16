// ============================================================
// Academix AI — Assignment detail (submit / grade)
// ============================================================
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/lib/api'
import type { Assignment, Submission } from '@/lib/types'
import { ArrowLeft, ClipboardList, Download, Upload } from 'lucide-react'
import { format } from 'date-fns'
import toast from 'react-hot-toast'

type AssignmentDetail = Assignment & {
  my_status?: string
  my_submitted_at?: string
  my_points?: number
  my_feedback?: string
  instructions?: string
}

export default function AssignmentPage() {
  const { courseId, assignmentId } = useParams<{ courseId: string; assignmentId: string }>()
  const { user } = useAuth()
  const navigate = useNavigate()

  const [assignment, setAssignment] = useState<AssignmentDetail | null>(null)
  const [submissions, setSubmissions] = useState<Submission[]>([])
  const [mySubmission, setMySubmission] = useState<Submission | null>(null)
  const [loading, setLoading] = useState(true)
  const [textResponse, setTextResponse] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [gradeDrafts, setGradeDrafts] = useState<Record<string, { points: string; feedback: string }>>({})

  const isStaff = user?.role === 'teacher' || user?.role === 'admin'
  const isStudent = user?.role === 'student'

  const load = async () => {
    if (!courseId || !assignmentId) return
    setLoading(true)
    try {
      const { data } = await api.get(`/classroom/${courseId}/assignments/${assignmentId}`)
      setAssignment(data)

      if (isStaff) {
        const subs = await api.get(`/classroom/${courseId}/assignments/${assignmentId}/submissions`)
        setSubmissions(subs.data || [])
        const drafts: Record<string, { points: string; feedback: string }> = {}
        for (const s of subs.data || []) {
          drafts[s.id] = {
            points: s.grade?.points_awarded?.toString() ?? '',
            feedback: s.grade?.feedback_text ?? '',
          }
        }
        setGradeDrafts(drafts)
      } else {
        const mine = await api.get(`/classroom/${courseId}/assignments/${assignmentId}/my-submission`)
        setMySubmission(mine.data || null)
        if (mine.data?.text_response) setTextResponse(mine.data.text_response)
      }
    } catch {
      toast.error('Could not load assignment')
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [courseId, assignmentId, user?.role])

  const submitWork = async () => {
    if (!courseId || !assignmentId) return
    if (!file && !textResponse.trim()) {
      toast.error('Attach a file or type a response')
      return
    }
    setSubmitting(true)
    try {
      const form = new FormData()
      if (file) form.append('file', file)
      if (textResponse.trim()) form.append('text_response', textResponse.trim())
      await api.post(`/classroom/${courseId}/assignments/${assignmentId}/submit`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      toast.success('Submitted')
      setFile(null)
      await load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Submission failed')
    }
    setSubmitting(false)
  }

  const unsubmit = async () => {
    if (!courseId || !assignmentId) return
    try {
      await api.post(`/classroom/${courseId}/assignments/${assignmentId}/unsubmit`)
      toast.success('Submission withdrawn')
      setTextResponse('')
      setFile(null)
      await load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Could not unsubmit')
    }
  }

  const gradeOne = async (submissionId: string) => {
    if (!courseId) return
    const draft = gradeDrafts[submissionId]
    const points = Number(draft?.points)
    if (Number.isNaN(points) || points < 0) {
      toast.error('Enter a valid score')
      return
    }
    try {
      await api.post(`/classroom/${courseId}/grades`, {
        submission_id: submissionId,
        points_awarded: points,
        feedback_text: draft?.feedback || null,
      })
      toast.success('Grade saved')
      await load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Grading failed')
    }
  }

  const downloadSubmission = async (submissionId: string) => {
    try {
      const { data } = await api.get(`/classroom/submissions/${submissionId}/download`)
      if (data.download_url) window.open(data.download_url, '_blank')
      else toast.error('No file attached')
    } catch {
      toast.error('Download failed')
    }
  }

  if (loading) return <div className="skeleton" style={{ height: 360, borderRadius: 12 }} />
  if (!assignment) {
    return (
      <div className="card" style={{ padding: 40, textAlign: 'center' }}>
        <p className="text-muted">Assignment not found</p>
        <button className="btn btn-ghost" onClick={() => navigate(-1)}>Go back</button>
      </div>
    )
  }

  const graded = mySubmission?.status === 'graded' || assignment.my_status === 'graded'
  const submitted = Boolean(mySubmission) && mySubmission!.status !== 'not_submitted'

  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <button className="btn btn-ghost" onClick={() => navigate(`/classroom/${courseId}`)}
        style={{ marginBottom: 12, padding: '4px 8px' }}>
        <ArrowLeft size={18} /> Back to course
      </button>

      <div className="card" style={{ padding: 24, marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <ClipboardList size={24} color="var(--color-primary)" />
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 22, marginBottom: 6 }}>{assignment.title}</h1>
            <p className="text-muted text-small">
              {assignment.due_at
                ? `Due ${format(new Date(assignment.due_at), 'MMM d, yyyy h:mm a')}`
                : 'No due date'}
              {' · '}{assignment.max_points} pts
            </p>
            {assignment.instructions && (
              <p style={{ marginTop: 14, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                {assignment.instructions}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Student turn-in */}
      {isStudent && (
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ marginBottom: 12 }}>Your work</h3>

          {graded && (
            <div style={{
              padding: 14, borderRadius: 8, marginBottom: 16,
              background: 'linear-gradient(135deg, #E6F4EA, #E8F0FE)',
            }}>
              <p className="font-medium">
                Grade: {assignment.my_points ?? mySubmission?.grade?.points_awarded ?? '—'} / {assignment.max_points}
              </p>
              {(assignment.my_feedback || mySubmission?.grade?.feedback_text) && (
                <p className="text-muted" style={{ marginTop: 6 }}>
                  {assignment.my_feedback || mySubmission?.grade?.feedback_text}
                </p>
              )}
            </div>
          )}

          {submitted && !graded && (
            <div style={{ marginBottom: 16 }}>
              <span className="badge badge-blue" style={{ textTransform: 'capitalize' }}>
                {mySubmission?.status || assignment.my_status}
              </span>
              {mySubmission?.submitted_at && (
                <span className="text-muted text-small" style={{ marginLeft: 8 }}>
                  {format(new Date(mySubmission.submitted_at), 'MMM d, h:mm a')}
                </span>
              )}
              {mySubmission?.file_name && (
                <p style={{ marginTop: 8 }}>
                  File: <strong>{mySubmission.file_name}</strong>{' '}
                  <button className="btn btn-ghost btn-icon" onClick={() => downloadSubmission(mySubmission.id)}>
                    <Download size={16} />
                  </button>
                </p>
              )}
              {mySubmission?.text_response && (
                <p style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{mySubmission.text_response}</p>
              )}
              <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={unsubmit}>
                Unsubmit
              </button>
            </div>
          )}

          {!graded && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div className="input-group">
                <label className="input-label">Written response</label>
                <textarea className="input" rows={4} value={textResponse}
                  onChange={e => setTextResponse(e.target.value)}
                  placeholder="Type your answer..."
                  disabled={submitted && !graded} />
              </div>
              <div className="input-group">
                <label className="input-label">Attach file (optional)</label>
                <input type="file" className="input" onChange={e => setFile(e.target.files?.[0] || null)}
                  disabled={submitted && !graded} />
              </div>
              <button className="btn btn-primary" onClick={submitWork}
                disabled={submitting || (submitted && !graded && !file && !textResponse.trim())}>
                <Upload size={16} /> {submitted ? 'Resubmit' : 'Turn in'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Teacher grading list */}
      {isStaff && (
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ marginBottom: 16 }}>
            Student work ({submissions.filter(s => s.status !== 'not_submitted').length} submitted)
          </h3>
          {submissions.length === 0 ? (
            <p className="text-muted">No enrolled students yet</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {submissions.map(s => (
                <div key={s.id || s.student_id} style={{
                  padding: 16, borderRadius: 10,
                  border: '1px solid var(--color-border)',
                }}>
                  <div className="flex-between" style={{ marginBottom: 8 }}>
                    <div>
                      <div className="font-medium">{s.student_name || 'Student'}</div>
                      <div className="text-muted text-small">{s.student_email}</div>
                    </div>
                    <span className={`badge ${s.status === 'graded' ? 'badge-green' : s.status === 'not_submitted' ? 'badge-gray' : 'badge-blue'}`}>
                      {s.status.replace('_', ' ')}
                    </span>
                  </div>

                  {s.status === 'not_submitted' ? (
                    <p className="text-muted text-small">Not submitted</p>
                  ) : (
                    <>
                      {s.text_response && (
                        <p style={{ marginBottom: 8, whiteSpace: 'pre-wrap' }}>{s.text_response}</p>
                      )}
                      {s.file_url && (
                        <button className="btn btn-ghost" onClick={() => downloadSubmission(s.id)}
                          style={{ marginBottom: 10 }}>
                          <Download size={14} /> {s.file_name || 'Download file'}
                        </button>
                      )}
                      <div className="grid-2" style={{ gap: 10 }}>
                        <div className="input-group">
                          <label className="input-label">Points (max {assignment.max_points})</label>
                          <input className="input" type="number" min={0} max={assignment.max_points} step={0.5}
                            value={gradeDrafts[s.id]?.points ?? ''}
                            onChange={e => setGradeDrafts(prev => ({
                              ...prev,
                              [s.id]: { ...prev[s.id], points: e.target.value, feedback: prev[s.id]?.feedback ?? '' },
                            }))} />
                        </div>
                        <div className="input-group">
                          <label className="input-label">Feedback</label>
                          <input className="input"
                            value={gradeDrafts[s.id]?.feedback ?? ''}
                            onChange={e => setGradeDrafts(prev => ({
                              ...prev,
                              [s.id]: { ...prev[s.id], feedback: e.target.value, points: prev[s.id]?.points ?? '' },
                            }))} />
                        </div>
                      </div>
                      <button className="btn btn-primary" style={{ marginTop: 10 }}
                        onClick={() => gradeOne(s.id)}>
                        Save grade
                      </button>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
