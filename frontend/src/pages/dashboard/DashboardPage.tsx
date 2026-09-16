// ============================================================
// Academix AI — Dashboard Router
// Routes to the correct dashboard based on user role
// ============================================================
import { useAuth } from '@/contexts/AuthContext'
import StudentDashboard from './StudentDashboard'
import TeacherDashboard from './TeacherDashboard'
import AdminDashboard from './AdminDashboard'

export default function DashboardPage() {
  const { user } = useAuth()

  if (user?.role === 'admin') return <AdminDashboard />
  if (user?.role === 'teacher') return <TeacherDashboard />
  return <StudentDashboard />
}
