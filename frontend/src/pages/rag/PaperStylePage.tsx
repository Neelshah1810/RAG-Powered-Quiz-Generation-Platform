// ============================================================
// Academix AI — Paper Style Page (Teacher)
// Same RAG engine, teacher-focused with draft/approve workflow
// ============================================================
import { useState, useEffect } from 'react'
import api from '@/lib/api'
import type { Course, GeneratedSet, GeneratedQuestion } from '@/lib/types'
import { formatSourceText } from '@/lib/types'
import { Sparkles, Send, BookOpen, ChevronDown, ChevronUp, CheckCircle, Edit3, Trash2, Download } from 'lucide-react'
import toast from 'react-hot-toast'

export default function PaperStylePage() {
  const [courses, setCourses] = useState<Course[]>([])
  const [selectedCourse, setSelectedCourse] = useState('')
  const [examType, setExamType] = useState('internal')
  const [topicInput, setTopicInput] = useState('')
  const [difficulty, setDifficulty] = useState('medium')
  const [questionCount, setQuestionCount] = useState(15)
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<GeneratedSet | null>(null)
  const [history, setHistory] = useState<GeneratedSet[]>([])
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({})
  const [editingQuestion, setEditingQuestion] = useState<string | null>(null)
  const [editText, setEditText] = useState('')

  useEffect(() => {
    api.get('/courses/').then(r => setCourses(r.data || []))
    api.get('/rag/sets', { params: { mode: 'paper_style' } }).then(r => setHistory(r.data || []))
  }, [])

  const generate = async () => {
    if (!selectedCourse) { toast.error('Select a course'); return }
    setGenerating(true); setResult(null)
    try {
      const { data } = await api.post('/rag/generate', {
        course_id: selectedCourse,
        mode: 'paper_style',
        exam_type: examType,
        topic_tags: topicInput ? topicInput.split(',').map(t => t.trim()) : [],
        difficulty,
        question_count: questionCount,
        question_types: ['mcq', 'short_answer', 'long_answer'],
      })
      setResult(data)
      toast.success(`Generated ${data.questions?.length || 0} questions (Draft)`)
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Generation failed')
    }
    setGenerating(false)
  }

  const approveSet = async () => {
    if (!result) return
    try {
      const { data } = await api.post(`/rag/sets/${result.id}/approve`, { status: 'approved' })
      setResult(data)
      toast.success('Paper draft approved! ✅')
    } catch { toast.error('Approval failed') }
  }

  const editQuestion = async (qId: string) => {
    try {
      await api.patch(`/rag/sets/${result!.id}/questions/${qId}`, { question_text: editText })
      // Refresh
      const { data } = await api.get(`/rag/sets/${result!.id}`)
      setResult(data)
      setEditingQuestion(null)
      toast.success('Question updated')
    } catch { toast.error('Update failed') }
  }

  const deleteQuestion = async (qId: string) => {
    try {
      await api.delete(`/rag/sets/${result!.id}/questions/${qId}`)
      const { data } = await api.get(`/rag/sets/${result!.id}`)
      setResult(data)
      toast.success('Question removed')
    } catch { toast.error('Delete failed') }
  }

  return (
    <div className="quiz-container">
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Sparkles size={28} color="#AB47BC" /> Paper Style
          </h1>
          <p className="text-muted" style={{ marginTop: 4 }}>Generate exam-ready question drafts — always reviewed before use</p>
        </div>
      </div>

      {/* Generation Config */}
      <div className="rag-prompt-area" style={{ marginBottom: 24, borderColor: '#AB47BC22' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="grid-3" style={{ gap: 12 }}>
            <div className="input-group">
              <label className="input-label">Course</label>
              <select className="input" value={selectedCourse} onChange={e => setSelectedCourse(e.target.value)}>
                <option value="">Select course...</option>
                {courses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div className="input-group">
              <label className="input-label">Exam Type</label>
              <select className="input" value={examType} onChange={e => setExamType(e.target.value)}>
                <option value="internal">Internal</option>
                <option value="external">External</option>
              </select>
            </div>
            <div className="input-group">
              <label className="input-label">Difficulty</label>
              <select className="input" value={difficulty} onChange={e => setDifficulty(e.target.value)}>
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </div>
          </div>
          <div className="input-group">
            <label className="input-label">Topics (optional)</label>
            <input className="input" placeholder="e.g. Unit 1, Unit 3"
              value={topicInput} onChange={e => setTopicInput(e.target.value)} />
          </div>
          <div className="flex-between">
            <div className="input-group" style={{ width: 120 }}>
              <label className="input-label">Questions</label>
              <input className="input" type="number" value={questionCount}
                onChange={e => setQuestionCount(Number(e.target.value))} min={5} max={50} />
            </div>
            <button className="btn btn-primary" onClick={generate} disabled={generating}
              style={{ background: '#AB47BC' }}>
              {generating ? '⟳ Generating...' : <><Send size={16} /> Generate Paper Draft</>}
            </button>
          </div>
        </div>
      </div>

      {generating && (
        <div className="card" style={{ padding: 40, textAlign: 'center' }}>
          <div style={{
            width: 48, height: 48, border: '3px solid var(--color-border)',
            borderTopColor: '#AB47BC', borderRadius: '50%',
            animation: 'spin 0.8s linear infinite', margin: '0 auto 16px',
          }} />
          <p className="font-medium">Generating paper draft...</p>
          <p className="text-muted text-small">Analyzing style profile & course material</p>
        </div>
      )}

      {/* Generated Result */}
      {result && (
        <div>
          {/* Status Banner */}
          <div className="card" style={{
            padding: 16, marginBottom: 20,
            background: result.status === 'approved' ? '#E6F4EA' : '#FEF7E0',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div>
              <span className={`badge ${result.status === 'approved' ? 'badge-green' : 'badge-yellow'}`} style={{ fontSize: 13 }}>
                {result.status === 'approved' ? '✅ Approved' : '📝 Draft — Needs Review'}
              </span>
              <span className="text-muted" style={{ marginLeft: 12 }}>
                {result.total_questions} questions · {result.total_marks} marks
              </span>
            </div>
            {result.status === 'draft' && (
              <button className="btn btn-primary" onClick={approveSet} style={{ background: '#0F9D58' }}>
                <CheckCircle size={16} /> Approve Set
              </button>
            )}
          </div>

          {/* Questions */}
          {result.questions?.map((q, idx) => (
            <div key={q.id} className={`question-card ${q.teacher_edited ? 'teacher-edited' : ''}`}
              style={{ marginBottom: 12 }}>
              <div className="flex-between" style={{ marginBottom: 8 }}>
                <span className="font-semibold">
                  Q{idx + 1}.
                  <span className="badge badge-ai" style={{ marginLeft: 8 }}>AI Generated</span>
                  {q.teacher_edited && <span className="badge badge-yellow" style={{ marginLeft: 4 }}>Edited</span>}
                </span>
                <div style={{ display: 'flex', gap: 6 }}>
                  <span className="badge badge-gray">{q.marks} marks</span>
                  {q.bloom_level && <span className="badge badge-purple">{q.bloom_level}</span>}
                  <span className="badge badge-blue">{q.question_type.replace('_', ' ')}</span>
                </div>
              </div>

              {editingQuestion === q.id ? (
                <div>
                  <textarea className="input" value={editText} onChange={e => setEditText(e.target.value)} rows={3} />
                  <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                    <button className="btn btn-primary btn-sm" onClick={() => editQuestion(q.id)}>Save</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditingQuestion(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <p style={{ lineHeight: 1.6 }}>{q.question_text}</p>
              )}

              {q.options && (
                <div style={{ marginTop: 8, paddingLeft: 16 }}>
                  {q.options.map((opt, i) => <div key={i} style={{ marginBottom: 2 }}>{opt}</div>)}
                </div>
              )}

              <div style={{ marginTop: 8, padding: '8px 12px', background: 'var(--color-surface-2)', borderRadius: 6, fontSize: 13 }}>
                <strong>Answer:</strong> {q.correct_answer}
              </div>

              {/* Actions */}
              {result.status === 'draft' && (
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button className="btn btn-ghost text-small" onClick={() => { setEditingQuestion(q.id); setEditText(q.question_text) }}>
                    <Edit3 size={14} /> Edit
                  </button>
                  <button className="btn btn-ghost text-small" style={{ color: 'var(--color-danger)' }} onClick={() => deleteQuestion(q.id)}>
                    <Trash2 size={14} /> Remove
                  </button>
                </div>
              )}

              {/* Sources */}
              {q.source_texts?.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <button className="btn btn-ghost text-small"
                    onClick={() => setExpandedSources(p => ({ ...p, [q.id]: !p[q.id] }))}>
                    <BookOpen size={14} /> Sources {expandedSources[q.id] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                  {expandedSources[q.id] && (
                    <div className="sources-panel" style={{ marginTop: 6 }}>
                      {q.source_texts.map((src, si) => (
                        <div key={si} className="source-chunk" style={{ whiteSpace: 'pre-wrap' }}>
                          {formatSourceText(src)}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* History */}
      {!result && history.length > 0 && (
        <div>
          <h3 style={{ marginBottom: 16 }}>Previous Drafts</h3>
          {history.map(s => (
            <div key={s.id} className="card" style={{ padding: 16, marginBottom: 8, cursor: 'pointer' }}
              onClick={async () => {
                const { data } = await api.get(`/rag/sets/${s.id}`)
                setResult(data)
              }}>
              <div className="flex-between">
                <div>
                  <span className="font-medium">{s.course_name || 'Course'}</span>
                  <span className="text-muted" style={{ marginLeft: 8 }}>{s.exam_type} exam · {s.total_questions} questions</span>
                </div>
                <span className={`badge ${s.status === 'approved' ? 'badge-green' : 'badge-yellow'}`}>{s.status}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
