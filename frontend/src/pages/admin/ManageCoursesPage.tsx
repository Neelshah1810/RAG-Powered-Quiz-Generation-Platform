// ============================================================
// Academix AI — Manage Courses Page (Admin)
// Course CRUD, enrollment, View Details modal
// ============================================================
import { useState, useEffect, useRef } from 'react'
import api from '@/lib/api'
import type { Course, User, Enrollment } from '@/lib/types'
import { Plus, Users, BookOpen, Eye, X, Trash2, UserPlus, ChevronDown, Check } from 'lucide-react'
import toast from 'react-hot-toast'

export default function ManageCoursesPage() {
  const [courses, setCourses] = useState<Course[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [showEnroll, setShowEnroll] = useState<string | null>(null)
  const [showDetails, setShowDetails] = useState<string | null>(null)
  const [allUsers, setAllUsers] = useState<User[]>([])
  const [enrollments, setEnrollments] = useState<Enrollment[]>([])

  const [formName, setFormName] = useState('')
  const [formCode, setFormCode] = useState('')
  const [formSemester, setFormSemester] = useState('')
  const [formDesc, setFormDesc] = useState('')

  // Enroll state — separate teacher (single) and student (multi-select)
  const [enrollTeacherId, setEnrollTeacherId] = useState('')
  const [enrollStudentIds, setEnrollStudentIds] = useState<string[]>([])
  const [enrolling, setEnrolling] = useState(false)
  const [studentSearchTerm, setStudentSearchTerm] = useState('')
  const [showStudentDropdown, setShowStudentDropdown] = useState(false)
  const studentDropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadCourses()
    api.get('/users/').then(r => setAllUsers(r.data || []))
  }, [])

  // Close student dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (studentDropdownRef.current && !studentDropdownRef.current.contains(e.target as Node)) {
        setShowStudentDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const loadCourses = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/courses/')
      setCourses(data || [])
    } catch { /* ignore */ }
    setLoading(false)
  }

  const loadEnrollments = async (courseId: string) => {
    try {
      const { data } = await api.get(`/courses/${courseId}/enrollments`)
      setEnrollments(data || [])
    } catch { setEnrollments([]) }
  }

  const createCourse = async () => {
    if (!formName || !formCode) { toast.error('Name and code are required'); return }
    try {
      await api.post('/courses/', {
        name: formName, code: formCode,
        semester: formSemester ? Number(formSemester) : null,
        description: formDesc || null,
      })
      toast.success('Course created')
      setShowCreate(false)
      setFormName(''); setFormCode(''); setFormSemester(''); setFormDesc('')
      loadCourses()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to create')
    }
  }

  // Enroll a single teacher
  const enrollTeacher = async (courseId: string) => {
    if (!enrollTeacherId) { toast.error('Select a teacher'); return }
    setEnrolling(true)
    try {
      await api.post(`/courses/${courseId}/enroll`, {
        course_id: courseId,
        user_id: enrollTeacherId,
        role: 'teacher',
      })
      toast.success('Teacher enrolled')
      setEnrollTeacherId('')
      loadCourses()
      if (showDetails === courseId) loadEnrollments(courseId)
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to enroll teacher')
    }
    setEnrolling(false)
  }

  // Enroll multiple students using bulk endpoint
  const enrollStudents = async (courseId: string) => {
    if (enrollStudentIds.length === 0) { toast.error('Select at least one student'); return }
    setEnrolling(true)
    try {
      if (enrollStudentIds.length === 1) {
        await api.post(`/courses/${courseId}/enroll`, {
          course_id: courseId,
          user_id: enrollStudentIds[0],
          role: 'student',
        })
      } else {
        await api.post(`/courses/${courseId}/enroll/bulk`, {
          user_ids: enrollStudentIds,
          role: 'student',
        })
      }
      toast.success(`${enrollStudentIds.length} student(s) enrolled`)
      setEnrollStudentIds([])
      setStudentSearchTerm('')
      loadCourses()
      if (showDetails === courseId) loadEnrollments(courseId)
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to enroll students')
    }
    setEnrolling(false)
  }

  const unenrollUser = async (courseId: string, userId: string, userName: string, role: string) => {
    if (!confirm(`Remove ${role} "${userName}" from this course?`)) return
    try {
      await api.delete(`/courses/${courseId}/enroll/${userId}`)
      toast.success(`${userName} removed`)
      loadEnrollments(courseId)
      loadCourses()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to remove')
    }
  }

  const deleteCourse = async (courseId: string, courseName: string) => {
    if (!confirm(`Delete course "${courseName}"? This cannot be undone and will remove all materials, assignments, and enrollments.`)) return
    try {
      await api.delete(`/courses/${courseId}`)
      toast.success('Course deleted')
      loadCourses()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to delete course')
    }
  }

  const openDetails = async (courseId: string) => {
    setShowDetails(courseId)
    await loadEnrollments(courseId)
  }

  const openEnrollModal = (courseId: string) => {
    setShowEnroll(courseId)
    setEnrollTeacherId('')
    setEnrollStudentIds([])
    setStudentSearchTerm('')
  }

  const detailCourse = courses.find(c => c.id === showDetails)
  const enrolledTeachers = enrollments.filter(e => e.role === 'teacher')
  const enrolledStudents = enrollments.filter(e => e.role === 'student')

  // Filter users for enrollment dropdowns — exclude already enrolled users
  const enrolledUserIds = new Set(enrollments.map(e => e.user_id))
  const availableTeachers = allUsers.filter(u => u.role === 'teacher' && !enrolledUserIds.has(u.id))
  const availableStudents = allUsers.filter(u => u.role === 'student' && !enrolledUserIds.has(u.id))

  // Filtered students for the multi-select dropdown search
  const filteredStudents = studentSearchTerm
    ? availableStudents.filter(u =>
        u.full_name.toLowerCase().includes(studentSearchTerm.toLowerCase()) ||
        u.email.toLowerCase().includes(studentSearchTerm.toLowerCase())
      )
    : availableStudents

  const toggleStudentSelection = (userId: string) => {
    setEnrollStudentIds(prev =>
      prev.includes(userId)
        ? prev.filter(id => id !== userId)
        : [...prev, userId]
    )
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Manage Courses</h1>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          <Plus size={16} /> New Course
        </button>
      </div>

      {loading ? (
        <div className="grid-3">
          {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 160 }} />)}
        </div>
      ) : courses.length === 0 ? (
        <div className="card flex-center" style={{ padding: 60, flexDirection: 'column', gap: 12 }}>
          <BookOpen size={48} color="var(--color-text-3)" />
          <p className="text-muted">No courses created yet</p>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>Create First Course</button>
        </div>
      ) : (
        <div className="grid-3">
          {courses.map(course => (
            <div key={course.id} className="card" style={{ overflow: 'hidden' }}>
              <div style={{ background: course.banner_color, padding: '16px 20px', color: 'white', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0, paddingRight: 8 }}>
                  <h3 style={{ color: 'white', fontSize: 16 }}>{course.name}</h3>
                  <p style={{ opacity: 0.8, fontSize: 12, marginTop: 2 }}>{course.code}</p>
                </div>
                <button
                  className="btn btn-ghost btn-icon"
                  style={{ color: 'white', padding: 4, height: 'auto', width: 'auto', opacity: 0.9 }}
                  title="Delete Course"
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteCourse(course.id, course.name)
                  }}
                >
                  <Trash2 size={16} />
                </button>
              </div>
              <div style={{ padding: 16 }}>
                <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                  <span className="badge badge-blue">{course.teacher_count || 0} teachers</span>
                  <span className="badge badge-green">{course.student_count || 0} students</span>
                </div>
                {course.semester && (
                  <p className="text-muted text-small">Semester {course.semester}</p>
                )}
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <button className="btn btn-secondary" style={{ flex: 1, justifyContent: 'center' }}
                    onClick={() => openDetails(course.id)}>
                    <Eye size={14} /> View Details
                  </button>
                  <button className="btn btn-secondary" style={{ flex: 1, justifyContent: 'center' }}
                    onClick={() => openEnrollModal(course.id)}>
                    <UserPlus size={14} /> Enroll
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* View Details Modal */}
      {showDetails && detailCourse && (
        <div className="modal-overlay" onClick={() => setShowDetails(null)}>
          <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 600 }}>
            <div className="modal-header">
              <div>
                <h3>{detailCourse.name}</h3>
                <span className="text-muted text-small">{detailCourse.code}{detailCourse.semester ? ` · Semester ${detailCourse.semester}` : ''}</span>
              </div>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowDetails(null)}>
                <X size={20} />
              </button>
            </div>
            <div className="modal-body" style={{ maxHeight: 460, overflowY: 'auto' }}>
              {/* Teachers Section */}
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                marginBottom: 10,
              }}>
                <h4 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Users size={16} color="var(--color-primary)" />
                  Teachers ({enrolledTeachers.length})
                </h4>
              </div>
              {enrolledTeachers.length === 0 ? (
                <p className="text-muted text-small" style={{ marginBottom: 20, paddingLeft: 4 }}>No teachers enrolled</p>
              ) : (
                <div style={{ marginBottom: 20 }}>
                  {enrolledTeachers.map(e => (
                    <div key={e.id} style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '10px 8px', borderBottom: '1px solid var(--color-border)',
                    }}>
                      <div className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>
                        {e.user_name?.charAt(0) || '?'}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="font-medium" style={{ fontSize: 14 }}>{e.user_name}</div>
                        <div className="text-muted text-small">{e.user_email}</div>
                      </div>
                      <button
                        className="btn btn-ghost btn-icon"
                        style={{ color: 'var(--color-danger)', flexShrink: 0 }}
                        title={`Remove ${e.user_name}`}
                        onClick={() => unenrollUser(showDetails!, e.user_id, e.user_name || 'user', 'teacher')}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Students Section */}
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                marginBottom: 10,
              }}>
                <h4 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Users size={16} color="var(--color-secondary)" />
                  Students ({enrolledStudents.length})
                </h4>
              </div>
              {enrolledStudents.length === 0 ? (
                <p className="text-muted text-small" style={{ paddingLeft: 4 }}>No students enrolled</p>
              ) : (
                <div>
                  {enrolledStudents.map(e => (
                    <div key={e.id} style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '10px 8px', borderBottom: '1px solid var(--color-border)',
                    }}>
                      <div className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>
                        {e.user_name?.charAt(0) || '?'}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="font-medium" style={{ fontSize: 14 }}>{e.user_name}</div>
                        <div className="text-muted text-small">{e.user_email}</div>
                      </div>
                      <button
                        className="btn btn-ghost btn-icon"
                        style={{ color: 'var(--color-danger)', flexShrink: 0 }}
                        title={`Remove ${e.user_name}`}
                        onClick={() => unenrollUser(showDetails!, e.user_id, e.user_name || 'user', 'student')}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowDetails(null)}>Close</button>
              <button className="btn btn-primary" onClick={() => {
                openEnrollModal(showDetails!)
                setShowDetails(null)
              }}>
                <UserPlus size={15} /> Enroll User
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Course Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Course</h3>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowCreate(false)}>✕</button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="input-group">
                <label className="input-label">Course Name *</label>
                <input className="input" value={formName} onChange={e => setFormName(e.target.value)}
                  placeholder="e.g. Data Structures & Algorithms" />
              </div>
              <div className="grid-2">
                <div className="input-group">
                  <label className="input-label">Course Code *</label>
                  <input className="input" value={formCode} onChange={e => setFormCode(e.target.value)}
                    placeholder="e.g. CS301" />
                </div>
                <div className="input-group">
                  <label className="input-label">Semester</label>
                  <input className="input" type="number" value={formSemester}
                    onChange={e => setFormSemester(e.target.value)} placeholder="e.g. 5" />
                </div>
              </div>
              <div className="input-group">
                <label className="input-label">Description</label>
                <textarea className="input" value={formDesc} onChange={e => setFormDesc(e.target.value)} rows={2} />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={createCourse}>Create</button>
            </div>
          </div>
        </div>
      )}

      {/* Enroll User Modal — two sections: Teacher (single) + Students (multi-select) */}
      {showEnroll && (
        <div className="modal-overlay" onClick={() => setShowEnroll(null)}>
          <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
            <div className="modal-header">
              <div>
                <h3>Enroll Users</h3>
                <span className="text-muted text-small">
                  {courses.find(c => c.id === showEnroll)?.name || 'Course'}
                </span>
              </div>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowEnroll(null)}>✕</button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

              {/* ── Teacher enrollment (single select) ── */}
              <div style={{
                padding: 16, borderRadius: 'var(--radius-md)',
                border: '1px solid var(--color-border)', background: 'var(--color-surface-2)',
              }}>
                <h4 style={{ fontSize: 14, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Users size={16} color="var(--color-primary)" /> Enroll Teacher
                </h4>
                <div style={{ display: 'flex', gap: 8 }}>
                  <select
                    className="input"
                    value={enrollTeacherId}
                    onChange={e => setEnrollTeacherId(e.target.value)}
                    style={{ flex: 1 }}
                  >
                    <option value="">Select a teacher...</option>
                    {availableTeachers.map(u => (
                      <option key={u.id} value={u.id}>
                        {u.full_name} ({u.email})
                      </option>
                    ))}
                  </select>
                  <button
                    className="btn btn-primary"
                    disabled={!enrollTeacherId || enrolling}
                    onClick={() => enrollTeacher(showEnroll!)}
                    style={{ whiteSpace: 'nowrap' }}
                  >
                    {enrolling ? '...' : 'Add'}
                  </button>
                </div>
                {availableTeachers.length === 0 && (
                  <p className="text-muted text-small" style={{ marginTop: 8 }}>
                    No teachers available to enroll. Create teacher accounts first.
                  </p>
                )}
              </div>

              {/* ── Student enrollment (multi-select) ── */}
              <div style={{
                padding: 16, borderRadius: 'var(--radius-md)',
                border: '1px solid var(--color-border)', background: 'var(--color-surface-2)',
              }}>
                <h4 style={{ fontSize: 14, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Users size={16} color="var(--color-secondary)" /> Enroll Students
                </h4>

                {/* Selected students chips */}
                {enrollStudentIds.length > 0 && (
                  <div style={{
                    display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10,
                  }}>
                    {enrollStudentIds.map(id => {
                      const u = allUsers.find(u => u.id === id)
                      return (
                        <span key={id} className="badge badge-green" style={{
                          display: 'inline-flex', alignItems: 'center', gap: 4,
                          padding: '4px 10px', cursor: 'pointer', fontSize: 12,
                        }}
                          onClick={() => toggleStudentSelection(id)}
                          title="Click to remove"
                        >
                          {u?.full_name || 'Unknown'}
                          <X size={12} />
                        </span>
                      )
                    })}
                  </div>
                )}

                {/* Multi-select dropdown */}
                <div ref={studentDropdownRef} style={{ position: 'relative' }}>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <div style={{ position: 'relative', flex: 1 }}>
                      <input
                        className="input"
                        placeholder={availableStudents.length === 0 ? 'No students available' : 'Search students...'}
                        value={studentSearchTerm}
                        onChange={e => {
                          setStudentSearchTerm(e.target.value)
                          setShowStudentDropdown(true)
                        }}
                        onFocus={() => setShowStudentDropdown(true)}
                        disabled={availableStudents.length === 0}
                        style={{ paddingRight: 32 }}
                      />
                      <ChevronDown
                        size={16}
                        style={{
                          position: 'absolute', right: 10, top: '50%',
                          transform: 'translateY(-50%)', color: 'var(--color-text-3)',
                          pointerEvents: 'none',
                        }}
                      />
                    </div>
                    <button
                      className="btn btn-primary"
                      disabled={enrollStudentIds.length === 0 || enrolling}
                      onClick={() => enrollStudents(showEnroll!)}
                      style={{ whiteSpace: 'nowrap' }}
                    >
                      {enrolling ? '...' : `Enroll (${enrollStudentIds.length})`}
                    </button>
                  </div>

                  {/* Dropdown list */}
                  {showStudentDropdown && availableStudents.length > 0 && (
                    <div style={{
                      position: 'absolute', left: 0, right: 64, top: '100%',
                      marginTop: 4, background: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 'var(--radius-sm)',
                      boxShadow: 'var(--shadow-2)',
                      maxHeight: 200, overflowY: 'auto', zIndex: 10,
                    }}>
                      {filteredStudents.length === 0 ? (
                        <div style={{ padding: '12px 16px' }} className="text-muted text-small">
                          No matching students found
                        </div>
                      ) : (
                        filteredStudents.map(u => {
                          const isSelected = enrollStudentIds.includes(u.id)
                          return (
                            <div
                              key={u.id}
                              onClick={() => toggleStudentSelection(u.id)}
                              style={{
                                display: 'flex', alignItems: 'center', gap: 10,
                                padding: '8px 12px', cursor: 'pointer',
                                background: isSelected ? 'var(--color-primary-bg)' : 'transparent',
                                borderBottom: '1px solid var(--color-border)',
                                transition: 'background 0.15s',
                              }}
                              onMouseEnter={e => {
                                if (!isSelected) (e.currentTarget.style.background = 'var(--color-surface-2)')
                              }}
                              onMouseLeave={e => {
                                e.currentTarget.style.background = isSelected ? 'var(--color-primary-bg)' : 'transparent'
                              }}
                            >
                              <div style={{
                                width: 18, height: 18, borderRadius: 4,
                                border: isSelected ? 'none' : '2px solid var(--color-border)',
                                background: isSelected ? 'var(--color-primary)' : 'transparent',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                flexShrink: 0,
                              }}>
                                {isSelected && <Check size={12} color="white" />}
                              </div>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div className="font-medium" style={{ fontSize: 13 }}>{u.full_name}</div>
                                <div className="text-muted" style={{ fontSize: 11 }}>{u.email}</div>
                              </div>
                            </div>
                          )
                        })
                      )}
                    </div>
                  )}
                </div>

                {availableStudents.length === 0 && (
                  <p className="text-muted text-small" style={{ marginTop: 8 }}>
                    No students available to enroll. Create student accounts first.
                  </p>
                )}
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowEnroll(null)}>Done</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
