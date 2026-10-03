// ============================================================
// Academix AI — Sidebar Navigation
// Fixed per-role nav per PRD §5, Google Workspace-style
// ============================================================
import { NavLink } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { useChat } from '@/contexts/ChatContext'
import {
  LayoutDashboard, Sparkles, BookOpen, Calendar,
  Bell, Users, GraduationCap, FileText, MessagesSquare
} from 'lucide-react'

const teacherNav = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/paper-style', label: 'Paper Style', icon: Sparkles },
  { to: '/classroom', label: 'Classroom', icon: BookOpen },
  { to: '/chat', label: 'Chat', icon: MessagesSquare },
  { to: '/scheduler', label: 'Scheduler', icon: Calendar },
  { to: '/notices', label: 'Notice Board', icon: Bell },
]

const studentNav = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/quiz', label: 'Quiz Generation', icon: Sparkles },
  { to: '/classroom', label: 'Classroom', icon: BookOpen },
  { to: '/chat', label: 'Chat', icon: MessagesSquare },
  { to: '/scheduler', label: 'Scheduler', icon: Calendar },
  { to: '/notices', label: 'Notice Board', icon: Bell },
]

const adminNav = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/paper-style', label: 'Paper Style', icon: Sparkles },
  { to: '/classroom', label: 'Classroom', icon: BookOpen },
  { to: '/chat', label: 'Chat', icon: MessagesSquare },
  { to: '/admin/users', label: 'Manage Users', icon: Users },
  { to: '/admin/courses', label: 'Manage Courses', icon: GraduationCap },
  { to: '/scheduler', label: 'Scheduler', icon: Calendar },
  { to: '/notices', label: 'Notice Board', icon: Bell },
]

export default function Sidebar() {
  const { user } = useAuth()
  const { totalUnread } = useChat()

  const navItems =
    user?.role === 'admin' ? adminNav :
    user?.role === 'teacher' ? teacherNav :
    user?.role === 'student' ? studentNav :
    []

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
            {item.to === '/chat' && totalUnread > 0 && (
              <span className="cx-unread cx-nav-badge">{totalUnread > 99 ? '99+' : totalUnread}</span>
            )}
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
          {user?.full_name ? user.full_name.trim().charAt(0).toUpperCase() : (user?.email ? user.email.trim().charAt(0).toUpperCase() : 'U')}
        </div>
        <div style={{ overflow: 'hidden', flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {user?.full_name || user?.email?.split('@')[0] || 'User'}
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-3)', textTransform: 'capitalize' }}>
            {user?.role}
          </div>
        </div>
      </div>
    </aside>
  )
}
