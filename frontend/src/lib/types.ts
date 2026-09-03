// ============================================================
// Academix AI — TypeScript Type Definitions
// ============================================================

// ── User / Auth ──────────────────────────────────────────────
export interface User {
  id: string
  email: string
  full_name: string
  role: 'admin' | 'teacher' | 'student'
  department?: string
  avatar_url?: string
  phone?: string
  created_at?: string
}

export interface AuthState {
  user: User | null
  accessToken: string | null
  isLoading: boolean
}

// ── Courses ──────────────────────────────────────────────────
export interface Department {
  id: string
  name: string
  code: string
}

export interface Course {
  id: string
  name: string
  code: string
  department_id?: string
  department_name?: string
  semester?: number
  description?: string
  banner_color: string
  created_by?: string
  teacher_count?: number
  student_count?: number
}

export interface Section {
  id: string
  course_id: string
  name: string
}

export interface Enrollment {
  id: string
  course_id: string
  user_id: string
  role: 'teacher' | 'student'
  section_id?: string
  user_name?: string
  user_email?: string
  course_name?: string
}

// ── Classroom ─────────────────────────────────────────────────
export interface Announcement {
  id: string
  course_id: string
  posted_by: string
  text: string
  attachment_urls: string[]
  posted_at: string
  author_name?: string
  author_avatar?: string
}

export interface Material {
  id: string
  course_id: string
  uploaded_by: string
  title: string
  description?: string
  file_url: string
  file_name: string
  file_size?: number
  topic_tag?: string
  created_at: string
  uploader_name?: string
  document_id?: string
  source_type?: string
  exam_type?: string
  year?: number
  ingestion_status?: string
  ingestion_error?: string
  chunk_count?: number
}

export interface Assignment {
  id: string
  course_id: string
  created_by: string
  title: string
  instructions?: string
  attachment_urls: string[]
  due_at?: string
  max_points: number
  topic_tag?: string
  created_at: string
  author_name?: string
  submission_count?: number
  graded_count?: number
}

export interface Submission {
  id: string
  assignment_id: string
  student_id: string
  file_url?: string
  file_name?: string
  text_response?: string
  submitted_at: string
  status: 'not_submitted' | 'submitted' | 'late' | 'graded'
  student_name?: string
  student_email?: string
  grade?: Grade
}

export interface Grade {
  id: string
  submission_id: string
  points_awarded: number
  feedback_text?: string
  graded_by: string
  graded_at: string
}

export interface StreamItem {
  id: string
  type: 'announcement' | 'material' | 'assignment'
  title?: string
  text?: string
  author_name?: string
  author_avatar?: string
  created_at: string
  due_at?: string
  file_url?: string
  file_name?: string
  max_points?: number
}

// ── Scheduler ─────────────────────────────────────────────────
export type EventType = 'lecture' | 'meeting' | 'exam' | 'assignment_due' | 'holiday' | 'other'

export interface CalendarEvent {
  id: string
  course_id?: string
  creator_id?: string
  title: string
  description?: string
  event_type: EventType
  start_at: string
  end_at: string
  color: string
  location?: string
  created_at?: string
  course_name?: string
  creator_name?: string
  semester?: string
}

// ── Notice Board ──────────────────────────────────────────────
export type NoticeType = 'announcement' | 'assignment' | 'grade' | 'event' | 'admin'

export interface Notice {
  id: string
  course_id?: string
  author_id?: string
  title: string
  body: string
  notice_type: NoticeType
  created_at: string
  is_read: boolean
  author_name?: string
  author_avatar?: string
  course_name?: string
}

// ── RAG Engine ────────────────────────────────────────────────
export type QuestionType = 'mcq' | 'short_answer' | 'long_answer' | 'true_false' | 'fill_blank'
export type BloomLevel = 'remember' | 'understand' | 'apply' | 'analyze' | 'evaluate' | 'create'
export type GenerationMode = 'quiz_generation' | 'paper_style'

/** Provenance chunk attached to a generated question (NotebookLM-style sources). */
export interface SourceChunk {
  text?: string
  document_name?: string
  page_ref?: string
  source_type?: string
  similarity?: number
}

export interface GeneratedQuestion {
  id: string
  set_id: string
  question_text: string
  question_type: QuestionType
  options?: string[]
  correct_answer: string
  explanation?: string
  marks: number
  bloom_level?: BloomLevel
  source_chunk_ids: string[]
  source_texts: Array<string | SourceChunk>
  faithfulness_score?: number
  teacher_edited: boolean
  question_order: number
}

/** Format a source entry for display (handles string or structured chunk). */
export function formatSourceText(src: string | SourceChunk): string {
  if (typeof src === 'string') return src
  const header = [src.document_name, src.page_ref].filter(Boolean).join(', ')
  const body = (src.text || '').trim()
  return header ? `${header}\n${body}` : body || JSON.stringify(src)
}

export interface GeneratedSet {
  id: string
  requested_by: string
  course_id: string
  mode: GenerationMode
  exam_type?: string
  topic_tags: string[]
  difficulty: string
  status: 'generating' | 'draft' | 'approved' | 'rejected'
  total_marks?: number
  total_questions?: number
  created_at: string
  approved_at?: string
  course_name?: string
  questions: GeneratedQuestion[]
}

export interface QuizAttempt {
  id: string
  student_id: string
  set_id: string
  answers: Record<string, string>
  score?: number
  total_marks?: number
  started_at: string
  submitted_at?: string
  status: 'in_progress' | 'submitted'
  questions: GeneratedQuestion[]
}

export interface StyleProfile {
  id: string
  course_id: string
  exam_type: string
  total_marks?: number
  duration_minutes?: number
  section_structure: any[]
  bloom_distribution: Record<string, number>
  confidence_score: number
  pyq_count: number
  last_computed_at: string
}

export interface ContentDocument {
  id: string
  course_id: string
  file_name: string
  source_type: 'notes' | 'textbook' | 'pyq'
  status: 'pending' | 'processing' | 'indexed' | 'failed'
  chunk_count: number
  created_at: string
  error_message?: string
}

// ── API Response ──────────────────────────────────────────────
export interface ApiError {
  detail: string
  status?: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
