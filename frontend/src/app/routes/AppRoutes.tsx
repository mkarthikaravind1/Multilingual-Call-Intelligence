import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'
import { ProtectedRoute } from '../auth/ProtectedRoute'
import { AppShell } from '../shell/AppShell'
import { DashboardPage } from '../pages/DashboardPage'
import { LiveCallPage } from '../pages/LiveCallPage'
import { CallHistoryPage } from '../pages/CallHistoryPage'
import { PostCallAnalysisPage } from '../pages/PostCallAnalysisPage'
import { AiImprovementCenterPage } from '../pages/AiImprovementCenterPage'
import { LoginPage } from '../pages/LoginPage'
import { AdministrationPage } from '../pages/AdministrationPage'
import { EscalationsPage } from '../pages/EscalationsPage'

function RootRedirect() {
  const { isAuthenticated } = useAuth()
  return <Navigate to={isAuthenticated ? '/dashboard' : '/login'} replace />
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  return session?.role === 'ADMIN' ? <>{children}</> : <Navigate to="/dashboard" replace />
}

function SupervisorOnly({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  const allowed = session?.role === 'SUPERVISOR' || session?.role === 'ADMIN'
  return allowed ? <>{children}</> : <Navigate to="/dashboard" replace />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <AppShell title="Dashboard" subtitle="Customer intelligence overview">
              <DashboardPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/live-call"
        element={
          <ProtectedRoute>
            <AppShell title="Live Call" subtitle="Real-time call intelligence workspace">
              <LiveCallPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/call-history"
        element={
          <ProtectedRoute>
            <AppShell title="Call History" subtitle="All recorded calls, newest first">
              <CallHistoryPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/post-call-analysis"
        element={
          <ProtectedRoute>
            <AppShell title="Post-call Analysis" subtitle="Summary, complaints and estimate for a call">
              <PostCallAnalysisPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/ai-improvement"
        element={
          <ProtectedRoute>
            <AppShell title="AI Improvement Center" subtitle="Learning evidence, patterns and improvement review">
              <AiImprovementCenterPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route
        path="/escalations"
        element={
          <ProtectedRoute>
            <SupervisorOnly>
              <AppShell title="Escalations" subtitle="Calls that need a supervisor, most severe first">
                <EscalationsPage />
              </AppShell>
            </SupervisorOnly>
          </ProtectedRoute>
        }
      />

      <Route
        path="/administration"
        element={
          <ProtectedRoute>
            <AdminOnly>
              <AppShell title="Administration" subtitle="Roles and user access">
                <AdministrationPage />
              </AppShell>
            </AdminOnly>
          </ProtectedRoute>
        }
      />

      <Route path="/" element={<RootRedirect />} />
      <Route path="*" element={<RootRedirect />} />
    </Routes>
  )
}
