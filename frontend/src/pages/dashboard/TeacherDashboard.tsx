// ============================================================
// Academix AI — Teacher Dashboard
// Quick-start: Paper Style, today's schedule, pending submissions
// ============================================================
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/lib/api'
import type { CalendarEvent, Course } from '@/lib/types'
import { Sparkles, BookOpen, Calendar, Users, ChevronRight } from 'lucide-react'
import { format } from 'date-fns'

export default function TeacherDashboard() {
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
          <p className="text-muted" style={{ marginTop: 4 }}>Your teaching overview</p>
        </div>
      </div>

      <div className="grid-3" style={{ marginBottom: 24 }}>
        {/* Quick Start: Manual Paper Style Entry */}
        <div
          className="card"
          style={{
            padding: 24,
            background: 'linear-gradient(135deg, #AB47BC, #7B1FA2)',
            color: 'white',
          }}
        >
          <Sparkles size={32} style={{ marginBottom: 12, opacity: 0.9 }} />
          <h3 style={{ color: 'white', fontSize: 18, marginBottom: 4 }}>Manual Paper Style</h3>
          <p style={{ opacity: 0.9, fontSize: 13, marginBottom: 14 }}>
            Configure paper blueprints & enter exam papers manually for Internal (30 marks) and External (70 marks)
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button
              className="btn btn-sm"
              style={{ background: 'white', color: '#7B1FA2', fontWeight: 600, border: 'none' }}
              onClick={() => navigate('/paper-style?preset=internal')}
            >
              Internal (30 Marks)
            </button>
            <button
              className="btn btn-sm"
              style={{ background: 'rgba(255,255,255,0.2)', color: 'white', border: '1px solid rgba(255,255,255,0.4)' }}
              onClick={() => navigate('/paper-style?preset=external')}
            >
              External (70 Marks)
            </button>
          </div>
        </div>

        <div className="card" style={{ padding: 24 }}>
          <BookOpen size={28} color="#4285F4" style={{ marginBottom: 12 }} />
          <h3 style={{ fontSize: 18, marginBottom: 8 }}>My Courses</h3>
          <p className="text-muted" style={{ fontSize: 32, fontWeight: 700 }}>{courses.length}</p>
          <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => navigate('/classroom')}>
            View Classroom
          </button>
        </div>

        <div className="card" style={{ padding: 24 }}>
          <Calendar size={28} color="#DB4437" style={{ marginBottom: 12 }} />
          <h3 style={{ fontSize: 18, marginBottom: 8 }}>Today's Events</h3>
          <p className="text-muted" style={{ fontSize: 32, fontWeight: 700 }}>{events.length}</p>
          <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => navigate('/scheduler')}>
            View Calendar
          </button>
        </div>
      </div>

      {/* Upcoming Events */}
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
                  background: event.color, flexShrink: 0,
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
