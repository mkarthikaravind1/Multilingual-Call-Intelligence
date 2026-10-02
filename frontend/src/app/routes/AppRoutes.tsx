import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useSearchParams } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'
import { ProtectedRoute } from '../auth/ProtectedRoute'
import { AppShell } from '../shell/AppShell'
import { DashboardPage } from '../pages/DashboardPage'
import { LiveCallPage } from '../pages/LiveCallPage'
import { PostCallAnalysisPage } from '../pages/PostCallAnalysisPage'
import { AiImprovementCenterPage } from '../pages/AiImprovementCenterPage'
import { LoginPage } from '../pages/LoginPage'
import { AdministrationPage } from '../pages/AdministrationPage'
import { EscalationsPage } from '../pages/EscalationsPage'
import { ComplaintsPage } from '../pages/ComplaintsPage'
import { isCallDetailsView } from '../features/live-call/liveCallMode'

// "Call details" for a call opened from a list, "Live Call" otherwise.
function LiveCallShell() {
  const [searchParams] = useSearchParams()
  const isDetails = isCallDetailsView(searchParams)
  return (
    <AppShell
      title={isDetails ? 'Call details' : 'Live Call'}
      subtitle={
        isDetails ? 'Transcript and analysis of this call' : 'Real-time call intelligence workspace'
      }
    >
      <LiveCallPage />
    </AppShell>
  )
}

// Call History was folded into the dashboard; old links still land somewhere
// useful (a single call opens its post-call analysis).
function CallHistoryRedirect() {
  const [searchParams] = useSearchParams()
  const callId = searchParams.get('call_id')?.trim()
  return (
    <Navigate
      to={
        callId ? `/post-call-analysis?call_id=${encodeURIComponent(callId)}` : '/dashboard'
      }
      replace
    />
  )
}

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
            <LiveCallShell />
          </ProtectedRoute>
        }
      />
      <Route
        path="/call-history"
        element={
          <ProtectedRoute>
            <CallHistoryRedirect />
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
        path="/complaints"
        element={
          <ProtectedRoute>
            <AppShell title="Complaints" subtitle="Every complaint from detection to closure, follow-ups first">
              <ComplaintsPage />
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
