// ============================================================
// Academix AI — Quiz Generation & RAG Chat Platform
// Full-width expanded interface, smart intent routing,
// grounded RAG tutor + interactive quiz generation
// ============================================================
import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import api from '@/lib/api'
import type { Course, GeneratedSet, GeneratedQuestion } from '@/lib/types'
import { formatSourceText } from '@/lib/types'
import {
  Sparkles, Send, BookOpen, ChevronDown, ChevronUp, RotateCcw,
  CheckCircle, XCircle, MessageSquare, Copy, User, HelpCircle, Plus, Book
} from 'lucide-react'
import toast from 'react-hot-toast'
import MarkdownRenderer from '@/components/common/MarkdownRenderer'

type ChatRole = 'user' | 'assistant' | 'system'

type ChatMessage =
  | { id: string; role: ChatRole; kind: 'text'; text: string; sources?: Array<Record<string, unknown> | string>; styleMeta?: Record<string, unknown> | null }
  | { id: string; role: 'assistant'; kind: 'quiz_form'; examType?: 'internal' | 'external' | ''; styleAware?: boolean; topics?: string }
  | { id: string; role: 'assistant'; kind: 'quiz'; set: GeneratedSet; attemptId: string | null }
  | { id: string; role: 'assistant'; kind: 'score'; score: number; total: number }
  | { id: string; role: 'assistant'; kind: 'typing' }

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

function isMcqCorrect(opt: string, correctAnswer: string): boolean {
  const ans = (correctAnswer || '').trim().toLowerCase()
  const option = (opt || '').trim().toLowerCase()
  if (!ans || !option) return false
  if (/^[a-d]$/.test(ans)) {
    return option.startsWith(`${ans})`) || option.startsWith(`${ans}.`) || option.startsWith(`${ans} `)
  }
  return option === ans || option.includes(ans)
}

export default function QuizGenerationPage() {
  const [courses, setCourses] = useState<Course[]>([])
  const [activeCourseId, setActiveCourseId] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)

  // Quiz form state
  const [formCourse, setFormCourse] = useState('')
  const [topicInput, setTopicInput] = useState('')
  const [difficulty, setDifficulty] = useState('medium')
  const [questionCount, setQuestionCount] = useState(5)
  const [questionTypes, setQuestionTypes] = useState<string[]>(['mcq', 'short_answer'])
  const [examType, setExamType] = useState<'internal' | 'external' | ''>('')
  const [styleAware, setStyleAware] = useState(false)
  const [generating, setGenerating] = useState(false)

  // Quiz attempt states
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [submittedSets, setSubmittedSets] = useState<Record<string, boolean>>({})
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({})
  const [attemptByMsg, setAttemptByMsg] = useState<Record<string, string | null>>({})

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const activeCourse = useMemo(
    () => courses.find(c => c.id === (activeCourseId || formCourse)),
    [courses, activeCourseId, formCourse],
  )

  useEffect(() => {
    api.get('/courses/').then(r => {
      const list: Course[] = r.data || []
      setCourses(list)
      if (list.length > 0) {
        setActiveCourseId(list[0].id)
        setFormCourse(list[0].id)
      }
    }).catch(() => {})

    setMessages([{
      id: uid(),
      role: 'assistant',
      kind: 'text',
      text:
        "Hi! I'm your **Academix RAG AI Tutor**. Ask me anything about your course material, like **\"explain merge sort\"**, **\"solve step by step\"**, or say **\"generate a quiz\"** to test your knowledge!",
    }])
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, generating])

  const push = (msg: ChatMessage) => setMessages(prev => [...prev, msg])
  const replaceTyping = (msg: ChatMessage) =>
    setMessages(prev => [...prev.filter(m => m.kind !== 'typing'), msg])

  const openQuizForm = (opts?: {
    examType?: 'internal' | 'external' | ''
    styleAware?: boolean
    topics?: string[]
  }) => {
    if (opts?.examType) setExamType(opts.examType)
    if (opts?.styleAware != null) setStyleAware(opts.styleAware)
    if (opts?.topics?.length) setTopicInput(opts.topics.join(', '))
    push({
      id: uid(),
      role: 'assistant',
      kind: 'quiz_form',
      examType: opts?.examType || '',
      styleAware: opts?.styleAware,
      topics: opts?.topics?.join(', '),
    })
  }

  const sendChat = async (rawText?: string) => {
    const text = (rawText ?? input).trim()
    if (!text || busy) return

    const selectedCourseId = activeCourseId || formCourse || (courses.length > 0 ? courses[0].id : '')
    if (!selectedCourseId) {
      toast.error('Please select a course first from the top bar.')
      return
    }

    setInput('')
    setBusy(true)
    push({ id: uid(), role: 'user', kind: 'text', text })
    push({ id: uid(), role: 'assistant', kind: 'typing' })

    try {
      const history = messages
        .filter((m): m is Extract<ChatMessage, { kind: 'text' }> => m.kind === 'text' && m.role !== 'system')
        .slice(-8)
        .map(m => ({ role: m.role as 'user' | 'assistant', content: m.text }))

      const { data } = await api.post('/rag/chat', {
        course_id: selectedCourseId,
        message: text,
        history,
      })

      setActiveCourseId(selectedCourseId)

      // Only open quiz form if backend specifically flags wants_quiz = true
      if (data.wants_quiz) {
        setFormCourse(selectedCourseId)
        if (data.exam_type) {
          setExamType(data.exam_type)
          setStyleAware(true)
        }
        if (data.topic_hints?.length) setTopicInput(data.topic_hints.join(', '))
        replaceTyping({ id: uid(), role: 'assistant', kind: 'text', text: data.reply, styleMeta: data.style_meta })
        openQuizForm({
          examType: data.exam_type || (data.intent === 'exam_prep' ? 'internal' : ''),
          styleAware: data.intent === 'exam_prep' || Boolean(data.exam_type),
          topics: data.topic_hints || [],
        })
      } else {
        replaceTyping({
          id: uid(),
          role: 'assistant',
          kind: 'text',
          text: data.reply,
          sources: data.sources || [],
          styleMeta: data.style_meta,
        })
      }
    } catch (err: any) {
      replaceTyping({
        id: uid(),
        role: 'assistant',
        kind: 'text',
        text: err.response?.data?.detail || 'Sorry — I could not process your request right now. Please try again.',
      })
    }
    setBusy(false)
  }

  const generateQuiz = async () => {
    const courseId = formCourse || activeCourseId
    if (!courseId) { toast.error('Select a course'); return }
    if (styleAware && !examType) { toast.error('Pick Internal or External exam type'); return }
    setGenerating(true)
    setBusy(true)
    const label = styleAware
      ? `Generate ${examType} exam-style practice quiz.`
      : 'Generate quiz with the selected settings.'
    push({ id: uid(), role: 'user', kind: 'text', text: label })
    push({ id: uid(), role: 'assistant', kind: 'typing' })

    try {
      const corpus = await api.get(`/rag/corpus/${courseId}`)
      if (!corpus.data?.ready) {
        replaceTyping({
          id: uid(),
          role: 'assistant',
          kind: 'text',
          text: corpus.data?.message
            || 'This course has no indexed material yet. Ask your teacher to upload notes in Classwork first.',
        })
        setGenerating(false)
        setBusy(false)
        return
      }

      const payload: Record<string, unknown> = {
        course_id: courseId,
        mode: 'quiz_generation',
        topic_tags: topicInput ? topicInput.split(',').map(t => t.trim()).filter(Boolean) : [],
        difficulty,
        question_count: questionCount,
        question_types: questionTypes,
        prompt: topicInput || undefined,
        style_aware: styleAware,
      }
      if (styleAware && examType) payload.exam_type = examType

      const { data } = await api.post('/rag/generate', payload)

      let attemptId: string | null = null
      try {
        const attempt = await api.post('/rag/attempts', { set_id: data.id })
        attemptId = attempt.data.id
      } catch { /* optional */ }

      const msgId = uid()
      setActiveCourseId(courseId)
      setAttemptByMsg(prev => ({ ...prev, [msgId]: attemptId }))
      setAnswers({})
      const styleNote = styleAware
        ? ` styled for **${examType}** exams (using paper pattern)`
        : ''
      replaceTyping({
        id: uid(),
        role: 'assistant',
        kind: 'text',
        text: `Here's a **${difficulty}** quiz with **${data.questions?.length || 0} question(s)**${styleNote}, grounded in course materials. Answer below and submit!`,
      })
      push({ id: msgId, role: 'assistant', kind: 'quiz', set: data, attemptId })
    } catch (err: any) {
      replaceTyping({
        id: uid(),
        role: 'assistant',
        kind: 'text',
        text: err.response?.data?.detail || 'Generation failed. Please check backend LLM status.',
      })
    }
    setGenerating(false)
    setBusy(false)
  }

  const submitQuiz = async (msg: Extract<ChatMessage, { kind: 'quiz' }>) => {
    const attemptId = attemptByMsg[msg.id] || msg.attemptId
    if (!attemptId) {
      toast.error('Could not start a quiz attempt — try generating again.')
      return
    }
    try {
      const { data } = await api.post(`/rag/attempts/${attemptId}/submit`, { answers })
      setSubmittedSets(prev => ({ ...prev, [msg.id]: true }))
      push({
        id: uid(),
        role: 'assistant',
        kind: 'score',
        score: data.score || 0,
        total: data.total_marks || 0,
      })
      toast.success('Quiz submitted successfully!')
    } catch {
      toast.error('Submission failed')
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendChat()
    }
  }

  return (
    <div className="quiz-chat-shell">
      {/* Header Bar */}
      <div className="quiz-chat-header-bar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: 12,
              background: 'linear-gradient(135deg, #4285F4, #1A73E8)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 12px rgba(66, 133, 244, 0.25)',
            }}
          >
            <Sparkles size={22} color="#ffffff" />
          </div>
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 700, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              Quiz Generation & RAG Chat
            </h1>
            <p className="text-muted text-small" style={{ margin: '2px 0 0' }}>
              Ask questions or create grounded practice quizzes from your course material
            </p>
          </div>
        </div>

        {/* Course Selector & New Quiz Action */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--color-surface-2)', padding: '4px 10px', borderRadius: 8, border: '1px solid var(--color-border)' }}>
            <Book size={14} color="var(--color-primary)" />
            <select
              style={{
                border: 'none',
                background: 'transparent',
                fontSize: 13.5,
                fontWeight: 600,
                color: 'var(--color-text)',
                outline: 'none',
                cursor: 'pointer',
              }}
              value={activeCourseId || formCourse}
              onChange={e => {
                const cid = e.target.value
                setActiveCourseId(cid)
                setFormCourse(cid)
              }}
            >
              <option value="">Select Course...</option>
              {courses.map(c => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.code})
                </option>
              ))}
            </select>
          </div>

          <button
            className="btn btn-primary btn-sm"
            style={{ gap: 6, padding: '8px 14px', borderRadius: 8 }}
            onClick={() => openQuizForm()}
          >
            <Plus size={15} /> Create Quiz
          </button>
        </div>
      </div>

      {/* Main Chat Window (Full Expanded Height & Width) */}
      <div className="quiz-chat-window">
        <div className="quiz-chat-messages">
          {messages.map(msg => {
            if (msg.kind === 'typing') {
              return (
                <div key={msg.id} className="chat-row assistant">
                  <div className="chat-avatar assistant-avatar">
                    <Sparkles size={16} />
                  </div>
                  <div className="chat-bubble assistant typing">
                    <span className="dot" /><span className="dot" /><span className="dot" />
                  </div>
                </div>
              )
            }

            if (msg.kind === 'text') {
              const isAssistant = msg.role === 'assistant'
              return (
                <div key={msg.id} className={`chat-row ${msg.role}`}>
                  {isAssistant && (
                    <div className="chat-avatar assistant-avatar">
                      <Sparkles size={16} />
                    </div>
                  )}
                  <div className={`chat-bubble ${msg.role}`}>
                    {isAssistant ? (
                      <MarkdownRenderer content={msg.text} />
                    ) : (
                      <div style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</div>
                    )}

                    {isAssistant && (
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 10,
                          marginTop: 12,
                          paddingTop: 10,
                          borderTop: '1px solid var(--color-border)',
                          flexWrap: 'wrap',
                        }}
                      >
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm text-small"
                          style={{ gap: 4 }}
                          onClick={() => {
                            navigator.clipboard.writeText(msg.text)
                            toast.success('Answer copied to clipboard!')
                          }}
                        >
                          <Copy size={13} /> Copy Answer
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm text-small"
                          style={{ color: 'var(--color-primary)', gap: 4, fontWeight: 600 }}
                          onClick={() => openQuizForm()}
                        >
                          <Sparkles size={13} /> Take Practice Quiz
                        </button>
                      </div>
                    )}

                    {msg.sources && msg.sources.length > 0 && (
                      <div style={{ marginTop: 12 }}>
                        <div className="text-muted text-small" style={{ marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4, fontWeight: 600 }}>
                          <BookOpen size={13} color="var(--color-primary)" /> Cited Course Material ({msg.sources.length} chunks)
                        </div>
                        <div className="sources-panel">
                          {msg.sources.map((src, i) => (
                            <div key={i} className="source-chunk" style={{ whiteSpace: 'pre-wrap' }}>
                              {formatSourceText(src as any)}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                  {!isAssistant && (
                    <div className="chat-avatar user-avatar">
                      <User size={16} />
                    </div>
                  )}
                </div>
              )
            }

            if (msg.kind === 'quiz_form') {
              return (
                <div key={msg.id} className="chat-row assistant">
                  <div className="chat-avatar assistant-avatar">
                    <Sparkles size={16} />
                  </div>
                  <div className="chat-bubble assistant quiz-form-card">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                      <div className="font-semibold" style={{ fontSize: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Sparkles size={18} color="var(--color-primary)" />
                        {styleAware ? 'Exam-Style Practice Quiz Builder' : 'Custom Quiz Builder'}
                      </div>
                      <span className="badge badge-blue">Interactive RAG</span>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                      <div className="grid-2" style={{ gap: 12 }}>
                        <div className="input-group">
                          <label className="input-label">Target Course</label>
                          <select className="input" value={formCourse || activeCourseId} onChange={e => setFormCourse(e.target.value)}>
                            <option value="">Select a course...</option>
                            {courses.map(c => (
                              <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                            ))}
                          </select>
                        </div>
                        <div className="input-group">
                          <label className="input-label">Difficulty Level</label>
                          <select className="input" value={difficulty} onChange={e => setDifficulty(e.target.value)}>
                            <option value="easy">Easy (Fundamentals)</option>
                            <option value="medium">Medium (Standard Exam)</option>
                            <option value="hard">Hard (Advanced Reasoning)</option>
                          </select>
                        </div>
                      </div>

                      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13.5, fontWeight: 500, cursor: 'pointer' }}>
                        <input type="checkbox" checked={styleAware}
                          onChange={e => {
                            setStyleAware(e.target.checked)
                            if (e.target.checked && !examType) setExamType('internal')
                            if (!e.target.checked) setExamType('')
                          }} />
                        Match course paper style (Internal / External exam pattern from PYQs)
                      </label>

                      {styleAware && (
                        <div className="input-group">
                          <label className="input-label">Exam Type Preset</label>
                          <select className="input" value={examType}
                            onChange={e => setExamType(e.target.value as 'internal' | 'external' | '')}>
                            <option value="internal">Internal Assessment (30 Marks Pattern)</option>
                            <option value="external">External End-Sem (70 Marks Pattern)</option>
                          </select>
                        </div>
                      )}

                      <div className="grid-2" style={{ gap: 12 }}>
                        <div className="input-group">
                          <label className="input-label">Specific Topics (optional)</label>
                          <input className="input" placeholder="e.g. Sorting, Trees, Memory Management"
                            value={topicInput} onChange={e => setTopicInput(e.target.value)} />
                        </div>
                        <div className="input-group">
                          <label className="input-label">Number of Questions</label>
                          <input className="input" type="number" min={1} max={20} value={questionCount}
                            onChange={e => setQuestionCount(Number(e.target.value) || 5)} />
                        </div>
                      </div>

                      <div>
                        <label className="input-label" style={{ marginBottom: 6 }}>Question Formats</label>
                        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                          {['mcq', 'short_answer', 'true_false', 'long_answer'].map(qt => (
                            <label key={qt} className={`badge ${questionTypes.includes(qt) ? 'badge-blue' : 'badge-gray'}`}
                              style={{ cursor: 'pointer', padding: '6px 14px', fontSize: 13, textTransform: 'capitalize' }}>
                              <input type="checkbox" hidden checked={questionTypes.includes(qt)}
                                onChange={() => {
                                  setQuestionTypes(prev =>
                                    prev.includes(qt) ? prev.filter(t => t !== qt) : [...prev, qt]
                                  )
                                }} />
                              {qt.replace('_', ' ')}
                            </label>
                          ))}
                        </div>
                      </div>

                      <button className="btn btn-primary" onClick={generateQuiz}
                        disabled={generating || (!formCourse && !activeCourseId) || questionTypes.length === 0 || (styleAware && !examType)}
                        style={{ alignSelf: 'flex-start', padding: '10px 22px', fontSize: 14 }}>
                        {generating
                          ? (styleAware ? 'Generating Exam-Style Quiz…' : 'Generating from Course Material…')
                          : <><Send size={15} /> {styleAware ? 'Generate Exam-Style Quiz' : 'Generate Quiz'}</>}
                      </button>
                    </div>
                  </div>
                </div>
              )
            }

            if (msg.kind === 'score') {
              return (
                <div key={msg.id} className="chat-row assistant">
                  <div className="chat-avatar assistant-avatar">
                    <Sparkles size={16} />
                  </div>
                  <div className="chat-bubble assistant score-card">
                    <h3 style={{ marginBottom: 6, fontSize: 18 }}>Quiz Completed</h3>
                    <p style={{ fontSize: 36, fontWeight: 800, color: 'var(--color-primary)', margin: '4px 0' }}>
                      {msg.score} / {msg.total}
                    </p>
                    <p className="text-muted" style={{ fontSize: 14 }}>
                      {Math.round((msg.score / Math.max(msg.total, 1)) * 100)}% score · Grounded in your course notes
                    </p>
                    <button className="btn btn-secondary" style={{ marginTop: 14, gap: 6 }}
                      onClick={() => openQuizForm({ styleAware, examType: examType || undefined })}>
                      <RotateCcw size={16} /> Take Another Quiz
                    </button>
                  </div>
                </div>
              )
            }

            if (msg.kind === 'quiz') {
              const submitted = Boolean(submittedSets[msg.id])
              return (
                <div key={msg.id} className="chat-row assistant">
                  <div className="chat-avatar assistant-avatar">
                    <Sparkles size={16} />
                  </div>
                  <div className="chat-bubble assistant quiz-thread" style={{ maxWidth: '100%', width: '100%' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                      {(msg.set.questions || []).map((q: GeneratedQuestion, idx: number) => (
                        <div key={q.id} className="question-card" style={{ padding: 18, border: '1px solid var(--color-border)', borderRadius: 12, background: 'var(--color-surface)' }}>
                          <div className="flex-between" style={{ marginBottom: 12 }}>
                            <span className="font-semibold" style={{ fontSize: 15 }}>
                              Question {idx + 1} <span className="badge badge-ai" style={{ marginLeft: 8 }}>Grounded RAG</span>
                            </span>
                            <div style={{ display: 'flex', gap: 6 }}>
                              <span className="badge badge-gray">{q.marks} {q.marks === 1 ? 'mark' : 'marks'}</span>
                              {q.bloom_level && <span className="badge badge-purple">{q.bloom_level}</span>}
                            </div>
                          </div>

                          <p style={{ marginBottom: 14, lineHeight: 1.6, fontSize: 15, fontWeight: 500 }}>{q.question_text}</p>

                          {q.question_type === 'mcq' && q.options && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                              {q.options.map((opt, oi) => {
                                const isSelected = answers[q.id] === opt
                                const isCorrect = submitted && isMcqCorrect(opt, q.correct_answer)
                                return (
                                  <label key={oi} style={{
                                    display: 'flex', alignItems: 'center', gap: 10,
                                    padding: '10px 14px', borderRadius: 8, cursor: submitted ? 'default' : 'pointer',
                                    border: `2px solid ${isSelected ? 'var(--color-primary)' : 'var(--color-border)'}`,
                                    background: submitted
                                      ? isCorrect ? '#E6F4EA' : isSelected ? '#FCE8E6' : 'white'
                                      : isSelected ? 'var(--color-primary-bg)' : 'white',
                                    transition: 'all 0.15s ease',
                                  }}>
                                    <input type="radio" name={`${msg.id}-${q.id}`} value={opt}
                                      checked={isSelected} disabled={submitted}
                                      onChange={() => setAnswers(prev => ({ ...prev, [q.id]: opt }))} />
                                    <span style={{ flex: 1, fontSize: 14 }}>{opt}</span>
                                    {submitted && isCorrect && <CheckCircle size={18} color="#0F9D58" />}
                                    {submitted && isSelected && !isCorrect && <XCircle size={18} color="#DB4437" />}
                                  </label>
                                )
                              })}
                            </div>
                          )}

                          {(q.question_type === 'short_answer' || q.question_type === 'fill_blank' || q.question_type === 'long_answer') && (
                            <textarea className="input" rows={2} placeholder="Type your answer here..."
                              value={answers[q.id] || ''} disabled={submitted}
                              onChange={e => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))} />
                          )}

                          {q.question_type === 'true_false' && (
                            <div style={{ display: 'flex', gap: 10 }}>
                              {['True', 'False'].map(opt => (
                                <button key={opt}
                                  className={`btn ${answers[q.id] === opt ? 'btn-primary' : 'btn-secondary'}`}
                                  disabled={submitted}
                                  style={{ padding: '8px 20px' }}
                                  onClick={() => setAnswers(prev => ({ ...prev, [q.id]: opt }))}>
                                  {opt}
                                </button>
                              ))}
                            </div>
                          )}

                          {submitted && (
                            <div style={{
                              marginTop: 14, padding: 14, borderRadius: 8,
                              background: '#F8FAFC', border: '1px solid #E2E8F0', fontSize: 13.5,
                            }}>
                              <p><strong>Correct Answer:</strong> {q.correct_answer}</p>
                              {q.explanation && <p style={{ marginTop: 6, color: '#475569' }}><strong>Explanation:</strong> {q.explanation}</p>}
                            </div>
                          )}

                          {q.source_texts && q.source_texts.length > 0 && (
                            <div style={{ marginTop: 12 }}>
                              <button className="btn btn-ghost text-small" style={{ gap: 4 }}
                                onClick={() => setExpandedSources(prev => ({ ...prev, [q.id]: !prev[q.id] }))}>
                                <BookOpen size={14} /> {expandedSources[q.id] ? 'Hide' : 'View'} Cited Material Excerpts
                                {expandedSources[q.id] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                              </button>
                              {expandedSources[q.id] && (
                                <div className="sources-panel" style={{ marginTop: 8 }}>
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

                      {!submitted && (msg.set.questions?.length || 0) > 0 && (
                        <button className="btn btn-primary" onClick={() => submitQuiz(msg)}
                          style={{ padding: '12px 32px', alignSelf: 'center', fontSize: 15, borderRadius: 10 }}>
                          Submit Practice Quiz
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            }

            return null
          })}
          <div ref={bottomRef} />
        </div>

        {/* Expanded Bottom Composer with Action Chips */}
        <div className="quiz-chat-composer">
          <div className="quick-prompts">
            {[
              'Generate a quiz',
              'Prepare me for internal exam',
              'Explain merge sort',
              'Solve step by step: time complexity of quicksort',
              'What should I revise?',
            ].map(p => (
              <button key={p} className="quick-prompt-btn"
                onClick={() => sendChat(p)} disabled={busy}>
                <Sparkles size={13} color="var(--color-primary)" />
                {p}
              </button>
            ))}
          </div>
          <div className="composer-row">
            <textarea
              ref={inputRef}
              className="input chat-input"
              rows={1}
              placeholder="Ask anything — 'explain merge sort', 'step by step...', 'prepare for internal exam'..."
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={busy}
            />
            <button
              className="btn btn-primary btn-icon"
              style={{ width: 48, height: 48, borderRadius: 12, flexShrink: 0 }}
              onClick={() => sendChat()}
              disabled={busy || !input.trim()}
              title="Send Message"
            >
              <Send size={19} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
