// ============================================================
// Academix AI — App Shell Layout
// Main layout wrapper with sidebar + topbar + content area
// ============================================================
import { Outlet, Navigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import Sidebar from './Sidebar'
import TopBar from './TopBar'

export default function AppShell() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex-center" style={{ minHeight: '100vh' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{
            width: 48, height: 48,
            border: '3px solid var(--color-border)',
            borderTopColor: 'var(--color-primary)',
            borderRadius: '50%',
            animation: 'spin 0.8s linear infinite',
            margin: '0 auto 16px',
          }} />
          <p className="text-muted">Loading Academix AI...</p>
        </div>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <TopBar />
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
