// ============================================================
// Academix AI — Top App Bar
// Google Workspace-style top bar with search + account
// ============================================================
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { Search, Bell, LogOut, Settings, User } from 'lucide-react'

export default function TopBar() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const [showMenu, setShowMenu] = useState(false)

  const handleLogout = async () => {
    await signOut()
    navigate('/login')
  }

  return (
    <header className="app-topbar">
      {/* Search */}
      <div style={{
        flex: 1,
        maxWidth: 560,
        position: 'relative'
      }}>
        <Search
          size={18}
          style={{
            position: 'absolute',
            left: 14,
            top: '50%',
            transform: 'translateY(-50%)',
            color: 'var(--color-text-3)',
          }}
        />
        <input
          className="input"
          placeholder="Search courses, assignments, quizzes..."
          style={{
            paddingLeft: 42,
            borderRadius: 24,
            background: 'var(--color-surface-2)',
            border: 'none',
          }}
        />
      </div>

      <div style={{ flex: 1 }} />

      {/* Notifications */}
      <button
        className="btn btn-icon btn-ghost"
        onClick={() => navigate('/notices')}
        title="Notifications"
        style={{ position: 'relative' }}
      >
        <Bell size={20} />
      </button>

      {/* Account menu */}
      <div style={{ position: 'relative' }}>
        <button
          className="avatar"
          onClick={() => setShowMenu(!showMenu)}
          style={{ cursor: 'pointer', border: 'none', fontSize: 14, width: 36, height: 36 }}
        >
          {user?.full_name ? user.full_name.trim().charAt(0).toUpperCase() : (user?.email ? user.email.trim().charAt(0).toUpperCase() : 'U')}
        </button>

        {showMenu && (
          <>
            <div
              style={{ position: 'fixed', inset: 0, zIndex: 999 }}
              onClick={() => setShowMenu(false)}
            />
            <div
              className="card card-elevated"
              style={{
                position: 'absolute',
                right: 0,
                top: 48,
                width: 240,
                zIndex: 1000,
                padding: '8px 0',
              }}
            >
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--color-border)' }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{user?.full_name}</div>
                <div className="text-muted text-small">{user?.email}</div>
                <span className="badge badge-blue" style={{ marginTop: 4 }}>
                  {user?.role}
                </span>
              </div>
              <button
                className="nav-item"
                onClick={() => { setShowMenu(false) }}
                style={{ width: '100%', margin: 0, borderRadius: 0 }}
              >
                <User size={18} />
                <span>Profile</span>
              </button>
              <button
                className="nav-item"
                onClick={() => { setShowMenu(false) }}
                style={{ width: '100%', margin: 0, borderRadius: 0 }}
              >
                <Settings size={18} />
                <span>Settings</span>
              </button>
              <div className="divider" style={{ margin: '4px 0' }} />
              <button
                className="nav-item"
                onClick={handleLogout}
                style={{ width: '100%', margin: 0, borderRadius: 0, color: 'var(--color-danger)' }}
              >
                <LogOut size={18} />
                <span>Sign out</span>
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  )
}
