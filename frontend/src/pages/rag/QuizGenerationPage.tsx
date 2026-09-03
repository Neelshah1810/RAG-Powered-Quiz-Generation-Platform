// ============================================================
// Academix AI — Quiz Generation (chat-first, RAG-grounded)
// Gemini-style conversation + interactive quiz cards in-thread
// ============================================================
import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import api from '@/lib/api'
import type { Course, GeneratedSet, GeneratedQuestion } from '@/lib/types'
import { formatSourceText } from '@/lib/types'
import {
  Sparkles, Send, BookOpen, ChevronDown, ChevronUp, RotateCcw,
  CheckCircle, XCircle, MessageSquare,
} from 'lucide-react'
import toast from 'react-hot-toast'

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
  // Model usually returns letter "A" / "B" …
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

  // Quiz form (shown inside chat when intent=quiz)
  const [formCourse, setFormCourse] = useState('')
  const [topicInput, setTopicInput] = useState('')
  const [difficulty, setDifficulty] = useState('medium')
  const [questionCount, setQuestionCount] = useState(5)
  const [questionTypes, setQuestionTypes] = useState<string[]>(['mcq', 'short_answer'])
  const [examType, setExamType] = useState<'internal' | 'external' | ''>('')
  const [styleAware, setStyleAware] = useState(false)
  const [generating, setGenerating] = useState(false)

  // Active quiz interaction state (keyed by message id)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [submittedSets, setSubmittedSets] = useState<Record<string, boolean>>({})
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({})
  const [attemptByMsg, setAttemptByMsg] = useState<Record<string, string | null>>({})

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const activeCourse = useMemo(
    () => courses.find(c => c.id === (formCourse || activeCourseId)),
    [courses, formCourse, activeCourseId],
  )

  useEffect(() => {
    api.get('/courses/').then(r => {
      const list = r.data || []
      setCourses(list)
      if (list.length === 1) {
        setActiveCourseId(list[0].id)
        setFormCourse(list[0].id)
      }
    })
    setMessages([{
      id: uid(),
      role: 'assistant',
      kind: 'text',
      text:
        "Hi — I'm your Academix RAG tutor. I can **explain concepts**, walk through **step-by-step** solutions, give **revision guidance**, or generate a **practice quiz**. Say **\"prepare me for internal exam\"** and I'll use this course's exam style (learned from past papers) without showing you the raw PYQs.",
    }])
  }, [])

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
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, generating])

  const push = (msg: ChatMessage) => setMessages(prev => [...prev, msg])
  const replaceTyping = (msg: ChatMessage) =>
    setMessages(prev => [...prev.filter(m => m.kind !== 'typing'), msg])

  const sendChat = async (raw?: string) => {
    const text = (raw ?? input).trim()
    if (!text || busy) return

    const courseId = formCourse || activeCourseId
    if (!courseId) {
      toast.error('Select a course first (in the quiz form or say which course).')
      push({ id: uid(), role: 'user', kind: 'text', text })
      push({
        id: uid(),
        role: 'assistant',
        kind: 'text',
        text: 'Which course should we use? Open the quiz form with **"generate a quiz"** and pick a course, or select one below.',
      })
      openQuizForm()
      setInput('')
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
        course_id: courseId,
        message: text,
        history,
      })

      setActiveCourseId(courseId)

      const wantsForm = data.wants_quiz || data.intent === 'quiz' || data.intent === 'quiz_practice' || data.intent === 'exam_prep'
      if (wantsForm) {
        setFormCourse(courseId)
        if (data.exam_type) {
          setExamType(data.exam_type)
          setStyleAware(true)
        } else if (data.intent === 'exam_prep') {
          setExamType('internal')
          setStyleAware(true)
        } else {
          setStyleAware(false)
          setExamType('')
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
        text: err.response?.data?.detail || 'Sorry — I could not reach the tutor just now. Try again.',
      })
    }
    setBusy(false)
  }

  const generateQuiz = async () => {
    if (!formCourse) { toast.error('Select a course'); return }
    if (styleAware && !examType) { toast.error('Pick Internal or External exam type'); return }
    setGenerating(true)
    setBusy(true)
    const label = styleAware
      ? `Generate ${examType} exam-style practice quiz.`
      : 'Generate quiz with the selected settings.'
    push({ id: uid(), role: 'user', kind: 'text', text: label })
    push({ id: uid(), role: 'assistant', kind: 'typing' })

    try {
      const corpus = await api.get(`/rag/corpus/${formCourse}`)
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
        course_id: formCourse,
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
      } catch { /* attempt is optional for viewing */ }

      const msgId = uid()
      setActiveCourseId(formCourse)
      setAttemptByMsg(prev => ({ ...prev, [msgId]: attemptId }))
      setAnswers({})
      const styleNote = styleAware
        ? ` styled for **${examType}** exams (using this course's paper pattern)`
        : ''
      replaceTyping({
        id: uid(),
        role: 'assistant',
        kind: 'text',
        text: `Here’s a ${difficulty} quiz with ${data.questions?.length || 0} question(s)${styleNote}, grounded in **${corpus.data.total_chunks}** chunk(s) from your materials. Answer below, then submit.`,
      })
      push({ id: msgId, role: 'assistant', kind: 'quiz', set: data, attemptId })
    } catch (err: any) {
      replaceTyping({
        id: uid(),
        role: 'assistant',
        kind: 'text',
        text: err.response?.data?.detail || 'Generation failed. Try broader topics or upload more material.',
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
      toast.success('Quiz submitted!')
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
      <div className="page-header" style={{ marginBottom: 12 }}>
        <div>
          <h1 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Sparkles size={28} color="#4285F4" /> Quiz Generation
          </h1>
          <p className="text-muted" style={{ marginTop: 4 }}>
            Chat about your notes, or ask for a quiz — answers are grounded in uploaded course material
            {activeCourse ? <> · <strong>{activeCourse.name}</strong></> : null}
          </p>
        </div>
        <button
          className="btn btn-secondary"
          onClick={() => openQuizForm()}
        >
          <MessageSquare size={16} /> New quiz
        </button>
      </div>

      <div className="quiz-chat-window">
        <div className="quiz-chat-messages">
          {messages.map(msg => {
            if (msg.kind === 'typing') {
              return (
                <div key={msg.id} className="chat-row assistant">
                  <div className="chat-bubble assistant typing">
                    <span className="dot" /><span className="dot" /><span className="dot" />
                  </div>
                </div>
              )
            }

            if (msg.kind === 'text') {
              return (
                <div key={msg.id} className={`chat-row ${msg.role}`}>
                  <div className={`chat-bubble ${msg.role}`}>
                    <div style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</div>
                    {msg.sources && msg.sources.length > 0 && (
                      <div style={{ marginTop: 10 }}>
                        <div className="text-muted text-small" style={{ marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
                          <BookOpen size={12} /> Sources
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
                </div>
              )
            }

            if (msg.kind === 'quiz_form') {
              return (
                <div key={msg.id} className="chat-row assistant">
                  <div className="chat-bubble assistant quiz-form-card">
                    <div className="font-semibold" style={{ marginBottom: 12 }}>
                      {styleAware ? 'Exam-style practice details' : 'Quiz details'}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      <div className="grid-2" style={{ gap: 10 }}>
                        <div className="input-group">
                          <label className="input-label">Course</label>
                          <select className="input" value={formCourse} onChange={e => setFormCourse(e.target.value)}>
                            <option value="">Select a course...</option>
                            {courses.map(c => (
                              <option key={c.id} value={c.id}>{c.name} ({c.code})</option>
                            ))}
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

                      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                        <input type="checkbox" checked={styleAware}
                          onChange={e => {
                            setStyleAware(e.target.checked)
                            if (e.target.checked && !examType) setExamType('internal')
                            if (!e.target.checked) setExamType('')
                          }} />
                        Match this course&apos;s paper style (Internal / External pattern from PYQs)
                      </label>

                      {styleAware && (
                        <div className="input-group">
                          <label className="input-label">Exam type</label>
                          <select className="input" value={examType}
                            onChange={e => setExamType(e.target.value as 'internal' | 'external' | '')}>
                            <option value="internal">Internal</option>
                            <option value="external">External</option>
                          </select>
                        </div>
                      )}

                      <div className="grid-2" style={{ gap: 10 }}>
                        <div className="input-group">
                          <label className="input-label">Topics (optional)</label>
                          <input className="input" placeholder="e.g. Sorting, Trees"
                            value={topicInput} onChange={e => setTopicInput(e.target.value)} />
                        </div>
                        <div className="input-group">
                          <label className="input-label">Question count</label>
                          <input className="input" type="number" min={1} max={20} value={questionCount}
                            onChange={e => setQuestionCount(Number(e.target.value) || 5)} />
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {['mcq', 'short_answer', 'true_false', 'long_answer'].map(qt => (
                          <label key={qt} className={`badge ${questionTypes.includes(qt) ? 'badge-blue' : 'badge-gray'}`}
                            style={{ cursor: 'pointer', padding: '4px 12px' }}>
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
                      <button className="btn btn-primary" onClick={generateQuiz}
                        disabled={generating || !formCourse || questionTypes.length === 0 || (styleAware && !examType)}
                        style={{ alignSelf: 'flex-start' }}>
                        {generating
                          ? (styleAware ? 'Generating exam-style quiz…' : 'Generating from your materials…')
                          : <><Send size={16} /> {styleAware ? 'Generate exam-style quiz' : 'Generate quiz'}</>}
                      </button>
                    </div>
                  </div>
                </div>
              )
            }

            if (msg.kind === 'score') {
              return (
                <div key={msg.id} className="chat-row assistant">
                  <div className="chat-bubble assistant score-card">
                    <h3 style={{ marginBottom: 6 }}>Quiz complete</h3>
                    <p style={{ fontSize: 32, fontWeight: 700, color: 'var(--color-primary)' }}>
                      {msg.score} / {msg.total}
                    </p>
                    <p className="text-muted">
                      {Math.round((msg.score / Math.max(msg.total, 1)) * 100)}% · grounded in your course notes
                    </p>
                    <button className="btn btn-secondary" style={{ marginTop: 12 }}
                      onClick={() => openQuizForm({ styleAware, examType: examType || undefined })}>
                      <RotateCcw size={16} /> Another quiz
                    </button>
                  </div>
                </div>
              )
            }

            if (msg.kind === 'quiz') {
              const submitted = Boolean(submittedSets[msg.id])
              return (
                <div key={msg.id} className="chat-row assistant">
                  <div className="chat-bubble assistant quiz-thread" style={{ maxWidth: '100%', width: '100%' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                      {(msg.set.questions || []).map((q: GeneratedQuestion, idx: number) => (
                        <div key={q.id} className="question-card">
                          <div className="flex-between" style={{ marginBottom: 12 }}>
                            <span className="font-semibold">
                              Q{idx + 1}. <span className="badge badge-ai">From your materials</span>
                            </span>
                            <div style={{ display: 'flex', gap: 6 }}>
                              <span className="badge badge-gray">{q.marks} {q.marks === 1 ? 'mark' : 'marks'}</span>
                              {q.bloom_level && <span className="badge badge-purple">{q.bloom_level}</span>}
                            </div>
                          </div>

                          <p style={{ marginBottom: 12, lineHeight: 1.6 }}>{q.question_text}</p>

                          {q.question_type === 'mcq' && q.options && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
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
                                  }}>
                                    <input type="radio" name={`${msg.id}-${q.id}`} value={opt}
                                      checked={isSelected} disabled={submitted}
                                      onChange={() => setAnswers(prev => ({ ...prev, [q.id]: opt }))} />
                                    <span style={{ flex: 1 }}>{opt}</span>
                                    {submitted && isCorrect && <CheckCircle size={18} color="#0F9D58" />}
                                    {submitted && isSelected && !isCorrect && <XCircle size={18} color="#DB4437" />}
                                  </label>
                                )
                              })}
                            </div>
                          )}

                          {(q.question_type === 'short_answer' || q.question_type === 'fill_blank') && (
                            <input className="input" placeholder="Type your answer..."
                              value={answers[q.id] || ''} disabled={submitted}
                              onChange={e => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))} />
                          )}

                          {q.question_type === 'true_false' && (
                            <div style={{ display: 'flex', gap: 8 }}>
                              {['True', 'False'].map(opt => (
                                <button key={opt}
                                  className={`btn ${answers[q.id] === opt ? 'btn-primary' : 'btn-secondary'}`}
                                  disabled={submitted}
                                  onClick={() => setAnswers(prev => ({ ...prev, [q.id]: opt }))}>
                                  {opt}
                                </button>
                              ))}
                            </div>
                          )}

                          {submitted && (
                            <div style={{
                              marginTop: 12, padding: 12, borderRadius: 8,
                              background: 'var(--color-surface-2)', fontSize: 13,
                            }}>
                              <p><strong>Correct Answer:</strong> {q.correct_answer}</p>
                              {q.explanation && <p style={{ marginTop: 4 }}><strong>Explanation:</strong> {q.explanation}</p>}
                            </div>
                          )}

                          {q.source_texts && q.source_texts.length > 0 && (
                            <div style={{ marginTop: 12 }}>
                              <button className="btn btn-ghost text-small"
                                onClick={() => setExpandedSources(prev => ({ ...prev, [q.id]: !prev[q.id] }))}>
                                <BookOpen size={14} /> {expandedSources[q.id] ? 'Hide' : 'View'} Sources
                                {expandedSources[q.id] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
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

                      {!submitted && (msg.set.questions?.length || 0) > 0 && (
                        <button className="btn btn-primary" onClick={() => submitQuiz(msg)}
                          style={{ padding: '12px 28px', alignSelf: 'center' }}>
                          Submit Quiz
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

        <div className="quiz-chat-composer">
          <div className="quick-prompts">
            {[
              'Generate a quiz',
              'Prepare me for internal exam',
              'Explain merge sort',
              'Solve step by step: time complexity of quicksort',
              'What should I revise?',
            ].map(p => (
              <button key={p} className="badge badge-gray" style={{ cursor: 'pointer', padding: '6px 12px' }}
                onClick={() => sendChat(p)} disabled={busy}>
                {p}
              </button>
            ))}
          </div>
          <div className="composer-row">
            <textarea
              ref={inputRef}
              className="input chat-input"
              rows={1}
              placeholder='Ask anything — or “prepare for external exam”, “explain…”, “step by step…”'
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={busy}
            />
            <button className="btn btn-primary btn-icon" onClick={() => sendChat()} disabled={busy || !input.trim()}
              title="Send">
              <Send size={18} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
