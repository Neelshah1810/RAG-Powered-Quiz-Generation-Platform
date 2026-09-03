// ============================================================
// Academix AI — App Router
// ============================================================
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { AuthProvider } from '@/contexts/AuthContext'
import AppShell from '@/components/layout/AppShell'
import RoleRoute from '@/components/RoleRoute'

// Pages
import LoginPage from '@/pages/auth/LoginPage'
import DashboardPage from '@/pages/dashboard/DashboardPage'
import ClassroomPage from '@/pages/classroom/ClassroomPage'
import CoursePage from '@/pages/classroom/CoursePage'
import AssignmentPage from '@/pages/classroom/AssignmentPage'
import QuizGenerationPage from '@/pages/rag/QuizGenerationPage'
import PaperStylePage from '@/pages/rag/PaperStylePage'
import SchedulerPage from '@/pages/scheduler/SchedulerPage'
import NoticeBoardPage from '@/pages/notices/NoticeBoardPage'
import ManageUsersPage from '@/pages/admin/ManageUsersPage'
import ManageCoursesPage from '@/pages/admin/ManageCoursesPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public */}
            <Route path="/login" element={<LoginPage />} />

            {/* Authenticated (App Shell) */}
            <Route element={<AppShell />}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/classroom" element={<ClassroomPage />} />
              <Route path="/classroom/:courseId" element={<CoursePage />} />
              <Route path="/classroom/:courseId/assignment/:assignmentId" element={<AssignmentPage />} />
              <Route path="/quiz" element={
                <RoleRoute roles={['student']}><QuizGenerationPage /></RoleRoute>
              } />
              <Route path="/paper-style" element={
                <RoleRoute roles={['teacher', 'admin']}><PaperStylePage /></RoleRoute>
              } />
              <Route path="/scheduler" element={<SchedulerPage />} />
              <Route path="/notices" element={<NoticeBoardPage />} />
              <Route path="/admin/users" element={
                <RoleRoute roles={['admin']}><ManageUsersPage /></RoleRoute>
              } />
              <Route path="/admin/courses" element={
                <RoleRoute roles={['admin']}><ManageCoursesPage /></RoleRoute>
              } />
            </Route>

            {/* Fallback */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>

      <Toaster
        position="bottom-right"
        toastOptions={{
          duration: 3000,
          style: {
            background: '#202124',
            color: '#fff',
            borderRadius: '8px',
            fontSize: '14px',
          },
        }}
      />
    </QueryClientProvider>
  )
}
