import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '../shell/AppShell'
import { DashboardPage } from '../pages/DashboardPage'
import { LiveCallPage } from '../pages/LiveCallPage'
import { CallHistoryPage } from '../pages/CallHistoryPage'
import { PostCallAnalysisPage } from '../pages/PostCallAnalysisPage'
import { AiImprovementCenterPage } from '../pages/AiImprovementCenterPage'
import { LoginPage } from '../pages/LoginPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/dashboard"
        element={
          <AppShell title="Dashboard" subtitle="Operational overview">
            <DashboardPage />
          </AppShell>
        }
      />
      <Route
        path="/live-call"
        element={
          <AppShell title="Live Call" subtitle="Operational workspace">
            <LiveCallPage />
          </AppShell>
        }
      />
      <Route
        path="/call-history"
        element={
          <AppShell title="Call History" subtitle="Search and review recent activity">
            <CallHistoryPage />
          </AppShell>
        }
      />
      <Route
        path="/post-call-analysis"
        element={
          <AppShell title="Post-call Analysis" subtitle="Review completed call intelligence">
            <PostCallAnalysisPage />
          </AppShell>
        }
      />
      <Route
        path="/ai-improvement"
        element={
          <AppShell title="AI Improvement Center" subtitle="Learning, evidence and review workflows">
            <AiImprovementCenterPage />
          </AppShell>
        }
      />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
