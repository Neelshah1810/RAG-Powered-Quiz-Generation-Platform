// ============================================================
// Academix AI — Admin Dashboard
// Institute-wide overview: user stats, course stats, activity
// ============================================================
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/lib/api'
import { Users, GraduationCap, Calendar, Bell, ChevronRight } from 'lucide-react'

export default function AdminDashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [stats, setStats] = useState({ total: 0, admins: 0, teachers: 0, students: 0 })
  const [courseCount, setCourseCount] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const [s, c] = await Promise.all([
          api.get('/users/stats/summary'),
          api.get('/courses/'),
        ])
        setStats(s.data)
        setCourseCount(c.data?.length || 0)
      } catch { /* ignore */ }
      setLoading(false)
    }
    load()
  }, [])

  const cards = [
    { label: 'Total Users', value: stats.total, icon: Users, color: '#4285F4', link: '/admin/users' },
    { label: 'Teachers', value: stats.teachers, icon: Users, color: '#0F9D58', link: '/admin/users?tab=teacher' },
    { label: 'Students', value: stats.students, icon: Users, color: '#AB47BC', link: '/admin/users?tab=student' },
    { label: 'Courses', value: courseCount, icon: GraduationCap, color: '#F4B400', link: '/admin/courses' },
  ]

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Admin Dashboard</h1>
          <p className="text-muted" style={{ marginTop: 4 }}>Institute overview</p>
        </div>
      </div>

      <div className="grid-4" style={{ marginBottom: 24 }}>
        {cards.map((card) => (
          <div
            key={card.label}
            className="card"
            style={{ padding: 24, cursor: 'pointer' }}
            onClick={() => navigate(card.link)}
          >
            <div className="flex-between" style={{ marginBottom: 16 }}>
              <card.icon size={24} color={card.color} />
              <ChevronRight size={16} color="var(--color-text-3)" />
            </div>
            <p className="text-muted text-small font-medium">{card.label}</p>
            <p style={{
              fontSize: 36, fontWeight: 700, color: card.color, marginTop: 4
            }}>
              {loading ? '—' : card.value}
            </p>
          </div>
        ))}
      </div>

      <div className="grid-2">
        <div className="card" style={{ padding: 24 }}>
          <h3 style={{ marginBottom: 16 }}>Quick Actions</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}
              onClick={() => navigate('/admin/users')}>
              <Users size={18} /> Manage Users
            </button>
            <button className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}
              onClick={() => navigate('/admin/courses')}>
              <GraduationCap size={18} /> Manage Courses
            </button>
            <button className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}
              onClick={() => navigate('/scheduler')}>
              <Calendar size={18} /> View Schedule
            </button>
            <button className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}
              onClick={() => navigate('/notices')}>
              <Bell size={18} /> Post Notice
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
