// ============================================================
// Academix AI — Paper Style Page (Teacher)
// Manual Paper Style Entry for Internal (30 Marks) & External (70 Marks)
// ============================================================
import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import api from '@/lib/api'
import type { Course, GeneratedSet } from '@/lib/types'
import { Sparkles, Plus, Trash2, Edit3, Save, CheckCircle, FileText, Download, Layers } from 'lucide-react'
import toast from 'react-hot-toast'

interface SectionConfig {
  id: string
  name: string
  question_type: string
  questions_to_attempt: number
  total_questions: number
  marks_per_question: number
  bloom_level: string
  topic_tag: string
}

interface QuestionInput {
  id: string
  section: string
  question_text: string
  question_type: string
  marks: number
  options: string[]
  correct_answer: string
  bloom_level: string
  topic_tag: string
}

const DEFAULT_INTERNAL_SECTIONS: SectionConfig[] = [
  {
    id: 'sec-1',
    name: 'Section A: Short Answer Questions',
    question_type: 'short_answer',
    questions_to_attempt: 5,
    total_questions: 5,
    marks_per_question: 2,
    bloom_level: 'remember',
    topic_tag: 'Unit 1 & 2',
  },
  {
    id: 'sec-2',
    name: 'Section B: Long Essay / Problem Solving',
    question_type: 'long_answer',
    questions_to_attempt: 2,
    total_questions: 3,
    marks_per_question: 10,
    bloom_level: 'apply',
    topic_tag: 'Unit 3 & 4',
  },
]

const DEFAULT_EXTERNAL_SECTIONS: SectionConfig[] = [
  {
    id: 'sec-1',
    name: 'Section A: Multiple Choice Questions (MCQs)',
    question_type: 'mcq',
    questions_to_attempt: 10,
    total_questions: 10,
    marks_per_question: 1,
    bloom_level: 'remember',
    topic_tag: 'All Units',
  },
  {
    id: 'sec-2',
    name: 'Section B: Short Analytical Questions',
    question_type: 'short_answer',
    questions_to_attempt: 5,
    total_questions: 6,
    marks_per_question: 4,
    bloom_level: 'understand',
    topic_tag: 'Units 1 - 3',
  },
  {
    id: 'sec-3',
    name: 'Section C: Comprehensive Essay & Case Studies',
    question_type: 'long_answer',
    questions_to_attempt: 4,
    total_questions: 5,
    marks_per_question: 10,
    bloom_level: 'analyze',
    topic_tag: 'Units 4 - 6',
  },
]

export default function PaperStylePage() {
  const [searchParams] = useSearchParams()
  const initialPreset = searchParams.get('preset') === 'external' ? 'external' : 'internal'

  const [courses, setCourses] = useState<Course[]>([])
  const [selectedCourse, setSelectedCourse] = useState('')
  const [examType, setExamType] = useState<'internal' | 'external'>(initialPreset)
  
  const [paperTitle, setPaperTitle] = useState(
    initialPreset === 'internal' ? 'Internal Assessment Test 1' : 'End Semester Final Examination'
  )
  const [totalMarks, setTotalMarks] = useState<number>(initialPreset === 'internal' ? 30 : 70)
  const [durationMinutes, setDurationMinutes] = useState<number>(initialPreset === 'internal' ? 60 : 180)
  const [passingMarks, setPassingMarks] = useState<number>(initialPreset === 'internal' ? 12 : 28)
  const [instructions, setInstructions] = useState('Read all questions carefully. Write neat answers with proper diagrams where required.')

  const [sections, setSections] = useState<SectionConfig[]>(
    initialPreset === 'internal' ? DEFAULT_INTERNAL_SECTIONS : DEFAULT_EXTERNAL_SECTIONS
  )
  
  const [questions, setQuestions] = useState<QuestionInput[]>([])
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<GeneratedSet | null>(null)
  const [history, setHistory] = useState<GeneratedSet[]>([])
  const [activeTab, setActiveTab] = useState<'builder' | 'history'>('builder')

  useEffect(() => {
    api.get('/courses/').then(r => {
      const list = r.data || []
      setCourses(list)
      if (list.length > 0) setSelectedCourse(list[0].id)
    })
    api.get('/rag/sets', { params: { mode: 'paper_style' } }).then(r => setHistory(r.data || []))
  }, [])

  const handleExamTypeChange = (type: 'internal' | 'external') => {
    setExamType(type)
    if (type === 'internal') {
      setTotalMarks(30)
      setDurationMinutes(60)
      setPassingMarks(12)
      setPaperTitle('Internal Assessment Test 1')
      setSections(DEFAULT_INTERNAL_SECTIONS)
    } else {
      setTotalMarks(70)
      setDurationMinutes(180)
      setPassingMarks(28)
      setPaperTitle('End Semester Final Examination')
      setSections(DEFAULT_EXTERNAL_SECTIONS)
    }
  }

  const calculatedSectionMarks = sections.reduce(
    (sum, s) => sum + s.questions_to_attempt * s.marks_per_question,
    0
  )

  const addSection = () => {
    const nextNum = sections.length + 1
    setSections(prev => [
      ...prev,
      {
        id: `sec-${Date.now()}`,
        name: `Section ${String.fromCharCode(64 + nextNum)}: Additional Section`,
        question_type: 'short_answer',
        questions_to_attempt: 2,
        total_questions: 2,
        marks_per_question: 5,
        bloom_level: 'understand',
        topic_tag: 'General',
      },
    ])
  }

  const removeSection = (id: string) => {
    setSections(prev => prev.filter(s => s.id !== id))
  }

  const updateSection = (id: string, field: keyof SectionConfig, value: any) => {
    setSections(prev =>
      prev.map(s => (s.id === id ? { ...s, [field]: value } : s))
    )
  }

  const addQuestion = (sectionName: string) => {
    setQuestions(prev => [
      ...prev,
      {
        id: `q-${Date.now()}`,
        section: sectionName,
        question_text: '',
        question_type: 'short_answer',
        marks: 2,
        options: ['', '', '', ''],
        correct_answer: '',
        bloom_level: 'remember',
        topic_tag: '',
      },
    ])
  }

  const updateQuestion = (id: string, field: keyof QuestionInput, value: any) => {
    setQuestions(prev =>
      prev.map(q => (q.id === id ? { ...q, [field]: value } : q))
    )
  }

  const removeQuestion = (id: string) => {
    setQuestions(prev => prev.filter(q => q.id !== id))
  }

  const saveManualPaperStyle = async (status: 'draft' | 'approved') => {
    if (!selectedCourse) {
      toast.error('Please select a course')
      return
    }
    setSaving(true)
    try {
      // 1. Save style profile blueprint
      await api.post('/rag/style-profile/manual', {
        course_id: selectedCourse,
        exam_type: examType,
        total_marks: totalMarks,
        duration_minutes: durationMinutes,
        passing_marks: passingMarks,
        instructions,
        section_structure: sections,
      })

      // 2. Save paper set with questions (if any entered)
      const { data } = await api.post('/rag/sets/manual', {
        course_id: selectedCourse,
        exam_type: examType,
        title: paperTitle,
        total_marks: totalMarks,
        duration_minutes: durationMinutes,
        status,
        instructions,
        section_structure: sections,
        questions: questions.map(q => ({
          question_text: q.question_text || 'Sample Question Text',
          question_type: q.question_type,
          marks: q.marks,
          section: q.section,
          options: q.question_type === 'mcq' ? q.options.filter(o => o.trim()) : undefined,
          correct_answer: q.correct_answer,
          bloom_level: q.bloom_level,
          topic_tag: q.topic_tag,
        })),
      })

      setResult(data)
      toast.success(`Paper Style (${examType.toUpperCase()} - ${totalMarks} Marks) saved successfully!`)
      api.get('/rag/sets', { params: { mode: 'paper_style' } }).then(r => setHistory(r.data || []))
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to save paper style')
    }
    setSaving(false)
  }

  const downloadPaperText = () => {
    if (!result) return
    const content = `
============================================================
${paperTitle.toUpperCase()}
Course: ${result.course_name || 'Course'} (${result.course_code || ''})
Exam Type: ${examType.toUpperCase()} | Total Marks: ${result.total_marks} | Duration: ${durationMinutes} Mins
============================================================

INSTRUCTIONS:
${instructions}

${result.questions && result.questions.length > 0 ? result.questions.map((q, idx) => `
Q${idx + 1}. [${q.section || 'General'}] (${q.marks} Marks)
${q.question_text}
${q.options ? q.options.map((opt, i) => `  ${String.fromCharCode(65 + i)}) ${opt}`).join('\n') : ''}
Answer Key: ${q.correct_answer || 'N/A'}
`).join('\n------------------------------------------------------------\n') : 'Section Breakdown:\n' + sections.map(s => `- ${s.name}: ${s.questions_to_attempt} Qs x ${s.marks_per_question} Marks = ${s.questions_to_attempt * s.marks_per_question} Marks`).join('\n')}
`
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${paperTitle.replace(/\s+/g, '_')}_${examType}_${totalMarks}M.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="quiz-container" style={{ maxWidth: 1000 }}>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Sparkles size={28} color="#AB47BC" /> Manual Paper Style Builder
          </h1>
          <p className="text-muted" style={{ marginTop: 4 }}>
            Direct manual entry of exam patterns and paper structures for <strong>Internal (30 Marks)</strong> and <strong>External (70 Marks)</strong> exams.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className={`btn ${activeTab === 'builder' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setActiveTab('builder')}
          >
            <Layers size={16} /> Paper Style Entry
          </button>
          <button
            className={`btn ${activeTab === 'history' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setActiveTab('history')}
          >
            <FileText size={16} /> Saved Papers ({history.length})
          </button>
        </div>
      </div>

      {activeTab === 'builder' && (
        <div>
          {/* Preset Selector */}
          <div className="card" style={{ padding: 20, marginBottom: 20, borderLeft: '4px solid #AB47BC' }}>
            <div className="flex-between" style={{ flexWrap: 'wrap', gap: 12 }}>
              <div>
                <span className="font-semibold" style={{ fontSize: 16 }}>Select Exam Pattern Preset</span>
                <p className="text-muted text-small" style={{ marginTop: 2 }}>
                  Choose standard Internal (30 marks) or External (70 marks) layout template:
                </p>
              </div>

              <div style={{ display: 'flex', gap: 10 }}>
                <button
                  type="button"
                  className="btn"
                  style={{
                    background: examType === 'internal' ? '#AB47BC' : 'var(--color-surface-2)',
                    color: examType === 'internal' ? 'white' : 'var(--color-text)',
                    padding: '10px 18px',
                    fontWeight: 600,
                    border: '1px solid #AB47BC44',
                  }}
                  onClick={() => handleExamTypeChange('internal')}
                >
                  📝 Internal Exam (30 Marks)
                </button>
                <button
                  type="button"
                  className="btn"
                  style={{
                    background: examType === 'external' ? '#7B1FA2' : 'var(--color-surface-2)',
                    color: examType === 'external' ? 'white' : 'var(--color-text)',
                    padding: '10px 18px',
                    fontWeight: 600,
                    border: '1px solid #7B1FA244',
                  }}
                  onClick={() => handleExamTypeChange('external')}
                >
                  🎓 External Exam (70 Marks)
                </button>
              </div>
            </div>
          </div>

          {/* Exam Details Form */}
          <div className="card" style={{ padding: 24, marginBottom: 24 }}>
            <h3 style={{ marginBottom: 16 }}>1. Paper & Course Information</h3>
            <div className="grid-3" style={{ gap: 16, marginBottom: 16 }}>
              <div className="input-group">
                <label className="input-label">Course</label>
                <select className="input" value={selectedCourse} onChange={e => setSelectedCourse(e.target.value)}>
                  {courses.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.code})
                    </option>
                  ))}
                </select>
              </div>

              <div className="input-group">
                <label className="input-label">Paper Title</label>
                <input className="input" value={paperTitle} onChange={e => setPaperTitle(e.target.value)} />
              </div>

              <div className="input-group">
                <label className="input-label">Exam Type</label>
                <select className="input" value={examType} onChange={e => handleExamTypeChange(e.target.value as any)}>
                  <option value="internal">Internal (30 Marks)</option>
                  <option value="external">External (70 Marks)</option>
                </select>
              </div>
            </div>

            <div className="grid-3" style={{ gap: 16, marginBottom: 16 }}>
              <div className="input-group">
                <label className="input-label">Total Marks</label>
                <input
                  type="number"
                  className="input"
                  value={totalMarks}
                  onChange={e => setTotalMarks(Number(e.target.value))}
                />
              </div>

              <div className="input-group">
                <label className="input-label">Duration (Minutes)</label>
                <input
                  type="number"
                  className="input"
                  value={durationMinutes}
                  onChange={e => setDurationMinutes(Number(e.target.value))}
                />
              </div>

              <div className="input-group">
                <label className="input-label">Passing Marks</label>
                <input
                  type="number"
                  className="input"
                  value={passingMarks}
                  onChange={e => setPassingMarks(Number(e.target.value))}
                />
              </div>
            </div>

            <div className="input-group">
              <label className="input-label">General Instructions</label>
              <textarea
                className="input"
                rows={2}
                value={instructions}
                onChange={e => setInstructions(e.target.value)}
              />
            </div>
          </div>

          {/* Section Blueprint Builder */}
          <div className="card" style={{ padding: 24, marginBottom: 24 }}>
            <div className="flex-between" style={{ marginBottom: 16 }}>
              <div>
                <h3>2. Section-wise Blueprint ({examType.toUpperCase()})</h3>
                <p className="text-muted text-small">Configure sections, question counts, and mark allocations.</p>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span
                  className={`badge ${
                    calculatedSectionMarks === totalMarks ? 'badge-green' : 'badge-yellow'
                  }`}
                  style={{ fontSize: 14, padding: '6px 12px' }}
                >
                  Section Total: {calculatedSectionMarks} / {totalMarks} Marks
                </span>
              </div>
            </div>

            {sections.map((sec, idx) => (
              <div
                key={sec.id}
                style={{
                  padding: 16,
                  borderRadius: 8,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-surface-2)',
                  marginBottom: 12,
                }}
              >
                <div className="flex-between" style={{ marginBottom: 12 }}>
                  <span className="font-semibold" style={{ color: '#AB47BC' }}>
                    Section {idx + 1}: {sec.name}
                  </span>
                  <button
                    className="btn btn-ghost btn-icon text-small"
                    style={{ color: 'var(--color-danger)' }}
                    onClick={() => removeSection(sec.id)}
                    title="Remove Section"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>

                <div className="grid-3" style={{ gap: 12, marginBottom: 10 }}>
                  <div className="input-group">
                    <label className="input-label">Section Title</label>
                    <input
                      className="input"
                      value={sec.name}
                      onChange={e => updateSection(sec.id, 'name', e.target.value)}
                    />
                  </div>

                  <div className="input-group">
                    <label className="input-label">Question Type</label>
                    <select
                      className="input"
                      value={sec.question_type}
                      onChange={e => updateSection(sec.id, 'question_type', e.target.value)}
                    >
                      <option value="mcq">MCQ</option>
                      <option value="short_answer">Short Answer</option>
                      <option value="long_answer">Long Answer / Essay</option>
                      <option value="true_false">True / False</option>
                    </select>
                  </div>

                  <div className="input-group">
                    <label className="input-label">Cognitive Demand (Bloom)</label>
                    <select
                      className="input"
                      value={sec.bloom_level}
                      onChange={e => updateSection(sec.id, 'bloom_level', e.target.value)}
                    >
                      <option value="remember">Remember</option>
                      <option value="understand">Understand</option>
                      <option value="apply">Apply</option>
                      <option value="analyze">Analyze</option>
                      <option value="evaluate">Evaluate</option>
                      <option value="create">Create</option>
                    </select>
                  </div>
                </div>

                <div className="grid-3" style={{ gap: 12 }}>
                  <div className="input-group">
                    <label className="input-label">Attempt Questions</label>
                    <input
                      type="number"
                      className="input"
                      value={sec.questions_to_attempt}
                      onChange={e => updateSection(sec.id, 'questions_to_attempt', Number(e.target.value))}
                    />
                  </div>

                  <div className="input-group">
                    <label className="input-label">Marks Per Question</label>
                    <input
                      type="number"
                      className="input"
                      value={sec.marks_per_question}
                      onChange={e => updateSection(sec.id, 'marks_per_question', Number(e.target.value))}
                    />
                  </div>

                  <div className="input-group">
                    <label className="input-label">Sub-Total Section Marks</label>
                    <div className="input" style={{ background: 'var(--color-surface)', fontWeight: 600 }}>
                      {sec.questions_to_attempt * sec.marks_per_question} Marks
                    </div>
                  </div>
                </div>
              </div>
            ))}

            <button className="btn btn-secondary" onClick={addSection} style={{ marginTop: 8 }}>
              <Plus size={16} /> Add Section
            </button>
          </div>

          {/* Manual Question Entry */}
          <div className="card" style={{ padding: 24, marginBottom: 24 }}>
            <div className="flex-between" style={{ marginBottom: 16 }}>
              <div>
                <h3>3. Manual Question Entry (Optional)</h3>
                <p className="text-muted text-small">Enter exact question texts and answers for this paper draft.</p>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                {sections.map(s => (
                  <button
                    key={s.id}
                    className="btn btn-secondary btn-sm"
                    onClick={() => addQuestion(s.name)}
                  >
                    <Plus size={14} /> Add Q to {s.name.split(':')[0]}
                  </button>
                ))}
              </div>
            </div>

            {questions.length === 0 ? (
              <div
                style={{
                  padding: 24,
                  textAlign: 'center',
                  background: 'var(--color-surface-2)',
                  borderRadius: 8,
                  color: 'var(--color-text-muted)',
                }}
              >
                No manual questions added yet. Click "+ Add Q" above to enter questions manually.
              </div>
            ) : (
              questions.map((q, qidx) => (
                <div
                  key={q.id}
                  style={{
                    padding: 16,
                    borderRadius: 8,
                    border: '1px solid var(--color-border)',
                    marginBottom: 12,
                  }}
                >
                  <div className="flex-between" style={{ marginBottom: 10 }}>
                    <span className="font-semibold">
                      Q{qidx + 1} ({q.section})
                    </span>
                    <button
                      className="btn btn-ghost btn-icon text-small"
                      style={{ color: 'var(--color-danger)' }}
                      onClick={() => removeQuestion(q.id)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>

                  <div className="input-group" style={{ marginBottom: 10 }}>
                    <label className="input-label">Question Text</label>
                    <textarea
                      className="input"
                      rows={2}
                      placeholder="Type question here..."
                      value={q.question_text}
                      onChange={e => updateQuestion(q.id, 'question_text', e.target.value)}
                    />
                  </div>

                  <div className="grid-3" style={{ gap: 10, marginBottom: 10 }}>
                    <div className="input-group">
                      <label className="input-label">Question Type</label>
                      <select
                        className="input"
                        value={q.question_type}
                        onChange={e => updateQuestion(q.id, 'question_type', e.target.value)}
                      >
                        <option value="short_answer">Short Answer</option>
                        <option value="long_answer">Long Answer</option>
                        <option value="mcq">MCQ</option>
                        <option value="true_false">True / False</option>
                      </select>
                    </div>

                    <div className="input-group">
                      <label className="input-label">Marks</label>
                      <input
                        type="number"
                        className="input"
                        value={q.marks}
                        onChange={e => updateQuestion(q.id, 'marks', Number(e.target.value))}
                      />
                    </div>

                    <div className="input-group">
                      <label className="input-label">Answer / Key</label>
                      <input
                        className="input"
                        placeholder="Model answer key"
                        value={q.correct_answer}
                        onChange={e => updateQuestion(q.id, 'correct_answer', e.target.value)}
                      />
                    </div>
                  </div>

                  {q.question_type === 'mcq' && (
                    <div style={{ marginTop: 8 }}>
                      <label className="input-label">MCQ Options (4 options)</label>
                      <div className="grid-2" style={{ gap: 8, marginTop: 4 }}>
                        {q.options.map((opt, optIdx) => (
                          <input
                            key={optIdx}
                            className="input"
                            placeholder={`Option ${String.fromCharCode(65 + optIdx)}`}
                            value={opt}
                            onChange={e => {
                              const newOpts = [...q.options]
                              newOpts[optIdx] = e.target.value
                              updateQuestion(q.id, 'options', newOpts)
                            }}
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Action Bar */}
          <div
            className="card"
            style={{
              padding: 20,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: '#F3E5F5',
              borderColor: '#AB47BC44',
            }}
          >
            <div>
              <span className="font-semibold" style={{ color: '#7B1FA2' }}>
                Ready to Save Paper Style
              </span>
              <p className="text-muted text-small" style={{ marginTop: 2 }}>
                Save as draft or approve for instant access and download.
              </p>
            </div>

            <div style={{ display: 'flex', gap: 12 }}>
              <button
                className="btn btn-secondary"
                onClick={() => saveManualPaperStyle('draft')}
                disabled={saving}
              >
                <Save size={16} /> Save Draft
              </button>
              <button
                className="btn btn-primary"
                style={{ background: '#7B1FA2' }}
                onClick={() => saveManualPaperStyle('approved')}
                disabled={saving}
              >
                <CheckCircle size={16} /> Save & Approve Paper
              </button>
            </div>
          </div>

          {/* Active Result View */}
          {result && (
            <div className="card" style={{ padding: 24, marginTop: 24, borderColor: '#0F9D58' }}>
              <div className="flex-between" style={{ marginBottom: 16 }}>
                <div>
                  <span className="badge badge-green">
                    ✅ {result.status === 'approved' ? 'Approved Paper' : 'Draft Paper'}
                  </span>
                  <h3 style={{ marginTop: 8 }}>{result.generation_config?.title || paperTitle}</h3>
                  <p className="text-muted text-small">
                    Total Marks: {result.total_marks} | Questions: {result.questions?.length || 0}
                  </p>
                </div>
                <button className="btn btn-secondary" onClick={downloadPaperText}>
                  <Download size={16} /> Download (.TXT)
                </button>
              </div>

              {result.questions && result.questions.length > 0 ? (
                <div>
                  {result.questions.map((q, i) => (
                    <div key={q.id || i} style={{ padding: '10px 0', borderBottom: '1px solid var(--color-border)' }}>
                      <div className="flex-between">
                        <strong>Q{i + 1}. {q.question_text}</strong>
                        <span className="badge badge-gray">{q.marks} marks</span>
                      </div>
                      {q.options && (
                        <div style={{ marginTop: 4, paddingLeft: 12, fontSize: 13 }}>
                          {q.options.map((o, oi) => (
                            <div key={oi}>{String.fromCharCode(65 + oi)}) {o}</div>
                          ))}
                        </div>
                      )}
                      {q.correct_answer && (
                        <div className="text-small text-muted" style={{ marginTop: 4 }}>
                          Answer Key: {q.correct_answer}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-muted text-small">
                  Saved Section Blueprint Structure. Download or export paper specification anytime.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* History View */}
      {activeTab === 'history' && (
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ marginBottom: 16 }}>Saved Paper Styles & Exam Sets</h3>
          {history.length === 0 ? (
            <p className="text-muted">No saved paper sets yet.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {history.map(s => (
                <div
                  key={s.id}
                  className="card"
                  style={{
                    padding: 16,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                    background: 'var(--color-surface-2)',
                  }}
                  onClick={async () => {
                    const { data } = await api.get(`/rag/sets/${s.id}`)
                    setResult(data)
                    setActiveTab('builder')
                  }}
                >
                  <div>
                    <div className="font-semibold">
                      {s.generation_config?.title || `${s.course_name || 'Course'} Paper`}
                    </div>
                    <div className="text-muted text-small" style={{ marginTop: 2 }}>
                      Exam Type: {s.exam_type?.toUpperCase()} · Total Marks: {s.total_marks} · {s.total_questions} Questions
                    </div>
                  </div>
                  <span className={`badge ${s.status === 'approved' ? 'badge-green' : 'badge-yellow'}`}>
                    {s.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
