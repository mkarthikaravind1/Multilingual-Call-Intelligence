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
import { PriceListPage } from '../pages/PriceListPage'
import { ReportsPage } from '../pages/ReportsPage'
import { LiveCallsPage } from '../pages/LiveCallsPage'
import { AuditLogPage } from '../pages/AuditLogPage'
import { AiLogPage } from '../pages/AiLogPage'
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

// The dashboard: staff work from it and an admin reads it. A management
// user is sent to the reports, the one place they have (every other guard
// sends a user it refuses to the dashboard, which brings them here).
function DashboardReaders({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  return session?.role === 'MANAGEMENT' ? <Navigate to="/reports" replace /> : <>{children}</>
}

// The pages for people who work on calls: executives and supervisors.
function StaffOnly({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  const allowed = session?.role === 'ICR' || session?.role === 'SUPERVISOR'
  return allowed ? <>{children}</> : <Navigate to="/dashboard" replace />
}

function ReportReaders({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  const allowed =
    session?.role === 'SUPERVISOR' || session?.role === 'ADMIN' || session?.role === 'MANAGEMENT'
  return allowed ? <>{children}</> : <Navigate to="/dashboard" replace />
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  return session?.role === 'ADMIN' ? <>{children}</> : <Navigate to="/dashboard" replace />
}

// Supervisors only; admins too are sent away.
function SupervisorOnly({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  return session?.role === 'SUPERVISOR' ? <>{children}</> : <Navigate to="/dashboard" replace />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <DashboardReaders>
              <AppShell title="Dashboard" subtitle="Customer intelligence overview">
                <DashboardPage />
              </AppShell>
            </DashboardReaders>
          </ProtectedRoute>
        }
      />
      <Route
        path="/live-call"
        element={
          <ProtectedRoute>
            <StaffOnly>
              <LiveCallShell />
            </StaffOnly>
          </ProtectedRoute>
        }
      />
      <Route
        path="/call-history"
        element={
          <ProtectedRoute>
            <DashboardReaders>
              <CallHistoryRedirect />
            </DashboardReaders>
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
            <StaffOnly>
              <AppShell title="Complaints" subtitle="Every complaint from detection to closure, follow-ups first">
                <ComplaintsPage />
              </AppShell>
            </StaffOnly>
          </ProtectedRoute>
        }
      />
      <Route
        path="/ai-improvement"
        element={
          <ProtectedRoute>
            <StaffOnly>
              <AppShell title="AI Improvement Center" subtitle="Learning evidence, patterns and improvement review">
                <AiImprovementCenterPage />
              </AppShell>
            </StaffOnly>
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
        path="/live-calls"
        element={
          <ProtectedRoute>
            <SupervisorOnly>
              <AppShell title="Live Calls" subtitle="Every call in progress, and the ones that need attention">
                <LiveCallsPage />
              </AppShell>
            </SupervisorOnly>
          </ProtectedRoute>
        }
      />

      <Route
        path="/reports"
        element={
          <ProtectedRoute>
            <ReportReaders>
              <AppShell title="Reports" subtitle="Complaint trends by category, location and executive">
                <ReportsPage />
              </AppShell>
            </ReportReaders>
          </ProtectedRoute>
        }
      />

      <Route
        path="/price-list"
        element={
          <ProtectedRoute>
            <SupervisorOnly>
              <AppShell title="Price List" subtitle="Service prices used for call estimates">
                <PriceListPage />
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
              <AppShell title="Administration" subtitle="Users, locations and the upkeep of the system">
                <AdministrationPage />
              </AppShell>
            </AdminOnly>
          </ProtectedRoute>
        }
      />

      <Route
        path="/administration/audit-log"
        element={
          <ProtectedRoute>
            <AdminOnly>
              <AppShell title="Audit Log" subtitle="Who did what, and when">
                <AuditLogPage />
              </AppShell>
            </AdminOnly>
          </ProtectedRoute>
        }
      />
      <Route
        path="/administration/ai-log"
        element={
          <ProtectedRoute>
            <AdminOnly>
              <AppShell title="AI Log" subtitle="What the AI was asked and what it answered, per call">
                <AiLogPage />
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
