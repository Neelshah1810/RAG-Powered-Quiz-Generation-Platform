// ============================================================
// Academix AI — Classroom Page
// Course grid with Google Classroom-style color banner cards
// ============================================================
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import type { Course } from '@/lib/types'
import { Users, BookOpen } from 'lucide-react'

export default function ClassroomPage() {
  const navigate = useNavigate()
  const [courses, setCourses] = useState<Course[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/courses/').then(r => setCourses(r.data || [])).finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Classroom</h1>
      </div>

      {loading ? (
        <div className="grid-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 180, borderRadius: 12 }} />
          ))}
        </div>
      ) : courses.length === 0 ? (
        <div className="card flex-center" style={{ padding: 60, flexDirection: 'column', gap: 12 }}>
          <BookOpen size={48} color="var(--color-text-3)" />
          <p className="text-muted">No courses found. Ask your admin to enroll you.</p>
        </div>
      ) : (
        <div className="grid-3">
          {courses.map((course) => (
            <div
              key={course.id}
              className="course-card"
              onClick={() => navigate(`/classroom/${course.id}`)}
            >
              <div
                className="course-card-banner"
                style={{ background: course.banner_color }}
              >
                <div>
                  <h3>{course.name}</h3>
                  <p style={{ color: 'rgba(255,255,255,.8)', fontSize: 12, marginTop: 2 }}>
                    {course.code} {course.semester ? `· Sem ${course.semester}` : ''}
                  </p>
                </div>
              </div>
              <div className="course-card-body">
                <div className="flex-between">
                  <span className="text-muted text-small">
                    {course.department_name || 'General'}
                  </span>
                  <div className="flex-center gap-8">
                    <span className="text-muted text-small flex-center gap-8">
                      <Users size={14} /> {(course.teacher_count || 0) + (course.student_count || 0)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
