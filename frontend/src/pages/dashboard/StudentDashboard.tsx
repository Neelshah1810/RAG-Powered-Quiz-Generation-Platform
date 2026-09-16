// ============================================================
// Academix AI — Student Dashboard
// Quick-start cards: upcoming events, pending assignments, quiz gen
// ============================================================
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/lib/api'
import type { CalendarEvent, Course } from '@/lib/types'
import { Sparkles, BookOpen, Calendar, Clock, ChevronRight } from 'lucide-react'
import { format } from 'date-fns'

export default function StudentDashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [courses, setCourses] = useState<Course[]>([])
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const [c, e] = await Promise.all([
          api.get('/courses/'),
          api.get('/scheduler/events', { params: { start_date: new Date().toISOString() } }),
        ])
        setCourses(c.data || [])
        setEvents((e.data || []).slice(0, 5))
      } catch { /* ignore */ }
      setLoading(false)
    }
    load()
  }, [])

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Welcome back, {user?.full_name?.split(' ')[0]}!</h1>
          <p className="text-muted" style={{ marginTop: 4 }}>Here's what's happening today</p>
        </div>
      </div>

      <div className="grid-3" style={{ marginBottom: 24 }}>
        {/* Quick Start: Quiz Generation */}
        <div
          className="card"
          style={{
            padding: 24,
            cursor: 'pointer',
            background: 'linear-gradient(135deg, #4285F4, #1a56c8)',
            color: 'white',
          }}
          onClick={() => navigate('/quiz')}
        >
          <Sparkles size={32} style={{ marginBottom: 12, opacity: 0.9 }} />
          <h3 style={{ color: 'white', fontSize: 18, marginBottom: 8 }}>Generate a Quiz</h3>
          <p style={{ opacity: 0.85, fontSize: 13, marginBottom: 16 }}>
            Practice with AI-generated questions from your course material
          </p>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            fontSize: 13, fontWeight: 500, opacity: 0.9,
          }}>
            Start now <ChevronRight size={16} />
          </span>
        </div>

        {/* My Courses */}
        <div className="card" style={{ padding: 24 }}>
          <BookOpen size={28} color="#0F9D58" style={{ marginBottom: 12 }} />
          <h3 style={{ fontSize: 18, marginBottom: 8 }}>My Courses</h3>
          <p className="text-muted" style={{ fontSize: 32, fontWeight: 700 }}>
            {courses.length}
          </p>
          <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => navigate('/classroom')}>
            View Classroom
          </button>
        </div>

        {/* Upcoming */}
        <div className="card" style={{ padding: 24 }}>
          <Calendar size={28} color="#DB4437" style={{ marginBottom: 12 }} />
          <h3 style={{ fontSize: 18, marginBottom: 8 }}>Upcoming Events</h3>
          <p className="text-muted" style={{ fontSize: 32, fontWeight: 700 }}>
            {events.length}
          </p>
          <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => navigate('/scheduler')}>
            View Calendar
          </button>
        </div>
      </div>

      {/* Upcoming Events List */}
      <div className="card" style={{ padding: 24 }}>
        <h3 style={{ marginBottom: 16 }}>Upcoming Schedule</h3>
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 48 }} />)}
          </div>
        ) : events.length === 0 ? (
          <p className="text-muted">No upcoming events</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {events.map((event) => (
              <div key={event.id} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '10px 12px', borderRadius: 8,
                background: 'var(--color-surface-2)',
              }}>
                <div style={{
                  width: 4, height: 36, borderRadius: 2,
                  background: event.color,
                  flexShrink: 0,
                }} />
                <div style={{ flex: 1 }}>
                  <div className="font-medium">{event.title}</div>
                  <div className="text-muted text-small">
                    {event.course_name} · {format(new Date(event.start_at), 'MMM d, h:mm a')}
                  </div>
                </div>
                <span className="badge badge-gray" style={{ textTransform: 'capitalize' }}>
                  {event.event_type.replace('_', ' ')}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
