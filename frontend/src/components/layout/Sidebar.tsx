// ============================================================
// Academix AI — Sidebar Navigation
// Fixed per-role nav per PRD §5, Google Workspace-style
// ============================================================
import { NavLink } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import {
  LayoutDashboard, Sparkles, BookOpen, Calendar,
  Bell, Users, GraduationCap, FileText
} from 'lucide-react'

const teacherNav = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/paper-style', label: 'Paper Style', icon: Sparkles },
  { to: '/classroom', label: 'Classroom', icon: BookOpen },
  { to: '/scheduler', label: 'Scheduler', icon: Calendar },
  { to: '/notices', label: 'Notice Board', icon: Bell },
]

const studentNav = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/quiz', label: 'Quiz Generation', icon: Sparkles },
  { to: '/classroom', label: 'Classroom', icon: BookOpen },
  { to: '/scheduler', label: 'Scheduler', icon: Calendar },
  { to: '/notices', label: 'Notice Board', icon: Bell },
]

const adminNav = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/classroom', label: 'Classroom', icon: BookOpen },
  { to: '/admin/users', label: 'Manage Users', icon: Users },
  { to: '/admin/courses', label: 'Manage Courses', icon: GraduationCap },
  { to: '/scheduler', label: 'Scheduler', icon: Calendar },
  { to: '/notices', label: 'Notice Board', icon: Bell },
]

export default function Sidebar() {
  const { user } = useAuth()

  const navItems =
    user?.role === 'admin' ? adminNav :
    user?.role === 'teacher' ? teacherNav :
    studentNav

  return (
    <aside className="app-sidebar">
      <div className="sidebar-logo">
        <GraduationCap size={28} color="#4285F4" />
        <span className="sidebar-logo-text">Academix AI</span>
      </div>

      <nav className="nav-items">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `nav-item ${isActive ? 'active' : ''}`
            }
          >
            <item.icon size={20} className="nav-icon" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* User info at bottom */}
      <div style={{
        padding: '16px 20px',
        borderTop: '1px solid var(--color-border)',
        display: 'flex',
        alignItems: 'center',
        gap: '12px'
      }}>
        <div className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>
          {user?.full_name?.charAt(0) || '?'}
        </div>
        <div style={{ overflow: 'hidden', flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {user?.full_name}
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-3)', textTransform: 'capitalize' }}>
            {user?.role}
          </div>
        </div>
      </div>
    </aside>
  )
}
