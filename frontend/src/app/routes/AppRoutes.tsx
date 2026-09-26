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

function RootRedirect() {
  const { isAuthenticated } = useAuth()
  return <Navigate to={isAuthenticated ? '/dashboard' : '/login'} replace />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <AppShell title="Dashboard" subtitle="Operational overview">
              <DashboardPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/live-call"
        element={
          <ProtectedRoute>
            <AppShell title="Live Call" subtitle="Operational workspace">
              <LiveCallPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/call-history"
        element={
          <ProtectedRoute>
            <AppShell title="Call History" subtitle="Search and review recent activity">
              <CallHistoryPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/post-call-analysis"
        element={
          <ProtectedRoute>
            <AppShell title="Post-call Analysis" subtitle="Review completed call intelligence">
              <PostCallAnalysisPage />
            </AppShell>
          </ProtectedRoute>
        }
      />
      <Route
        path="/ai-improvement"
        element={
          <ProtectedRoute>
            <AppShell title="AI Improvement Center" subtitle="Learning, evidence and review workflows">
              <AiImprovementCenterPage />
            </AppShell>
          </ProtectedRoute>
        }
      />

      <Route path="/" element={<RootRedirect />} />
      <Route path="*" element={<RootRedirect />} />
    </Routes>
  )
}
