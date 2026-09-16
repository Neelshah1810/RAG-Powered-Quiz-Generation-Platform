// ============================================================
// Academix AI — Role-gated route wrapper
// ============================================================
import { Navigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import type { User } from '@/lib/types'

type Role = User['role']

export default function RoleRoute({
  roles,
  children,
}: {
  roles: Role[]
  children: React.ReactNode
}) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  if (!roles.includes(user.role)) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}
