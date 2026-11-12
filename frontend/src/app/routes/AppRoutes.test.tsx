import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from './AppRoutes'

// Each page is replaced by a label, so these tests check only who may reach
// which page and where everyone else is sent.
const auth = vi.hoisted(() => ({
  isAuthenticated: true,
  session: { role: 'ICR' } as { role: string } | null,
}))
vi.mock('../auth/useAuth', () => ({ useAuth: () => auth }))
vi.mock('../shell/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

const { stub } = vi.hoisted(() => ({
  stub: (name: string) => () => <p>page:{name}</p>,
}))
vi.mock('../pages/DashboardPage', () => ({ DashboardPage: stub('dashboard') }))
vi.mock('../pages/LiveCallPage', () => ({ LiveCallPage: stub('live-call') }))
vi.mock('../pages/PostCallAnalysisPage', () => ({ PostCallAnalysisPage: stub('post-call') }))
vi.mock('../pages/AiImprovementCenterPage', () => ({ AiImprovementCenterPage: stub('ai-improvement') }))
vi.mock('../pages/LoginPage', () => ({ LoginPage: stub('login') }))
vi.mock('../pages/AdministrationPage', () => ({ AdministrationPage: stub('administration') }))
vi.mock('../pages/EscalationsPage', () => ({ EscalationsPage: stub('escalations') }))
vi.mock('../pages/ComplaintsPage', () => ({ ComplaintsPage: stub('complaints') }))
vi.mock('../pages/PriceListPage', () => ({ PriceListPage: stub('price-list') }))
vi.mock('../pages/ReportsPage', () => ({ ReportsPage: stub('reports') }))
vi.mock('../pages/LiveCallsPage', () => ({ LiveCallsPage: stub('live-calls') }))
vi.mock('../pages/AuditLogPage', () => ({ AuditLogPage: stub('audit-log') }))
vi.mock('../pages/AiLogPage', () => ({ AiLogPage: stub('ai-log') }))

type Role = 'ICR' | 'SUPERVISOR' | 'ADMIN' | 'MANAGEMENT'

function visit(path: string, role: Role | null) {
  auth.isAuthenticated = role !== null
  auth.session = role ? { role } : null
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  auth.isAuthenticated = true
  auth.session = { role: 'ICR' }
})

// path -> the roles that get the page itself.
const ACCESS: Record<string, { page: string; roles: Role[] }> = {
  '/live-call': { page: 'live-call', roles: ['ICR', 'SUPERVISOR'] },
  '/complaints': { page: 'complaints', roles: ['ICR', 'SUPERVISOR'] },
  '/ai-improvement': { page: 'ai-improvement', roles: ['ICR', 'SUPERVISOR'] },
  '/escalations': { page: 'escalations', roles: ['SUPERVISOR'] },
  '/live-calls': { page: 'live-calls', roles: ['SUPERVISOR'] },
  '/price-list': { page: 'price-list', roles: ['SUPERVISOR'] },
  '/reports': { page: 'reports', roles: ['SUPERVISOR', 'ADMIN', 'MANAGEMENT'] },
  '/administration': { page: 'administration', roles: ['ADMIN'] },
  '/administration/audit-log': { page: 'audit-log', roles: ['ADMIN'] },
  '/administration/ai-log': { page: 'ai-log', roles: ['ADMIN'] },
  '/post-call-analysis': { page: 'post-call', roles: ['ICR', 'SUPERVISOR', 'ADMIN', 'MANAGEMENT'] },
}

const ROLES: Role[] = ['ICR', 'SUPERVISOR', 'ADMIN', 'MANAGEMENT']

describe('route access by role', () => {
  for (const [path, { page, roles }] of Object.entries(ACCESS)) {
    for (const role of ROLES) {
      const allowed = roles.includes(role)
      it(`${role} ${allowed ? 'can open' : 'cannot open'} ${path}`, () => {
        visit(path, role)

        if (allowed) {
          expect(screen.getByText(`page:${page}`)).toBeInTheDocument()
        } else {
          expect(screen.queryByText(`page:${page}`)).toBeNull()
        }
      })
    }
  }

  it('sends a refused ICR, supervisor or admin to the dashboard', () => {
    visit('/administration', 'ICR')
    expect(screen.getByText('page:dashboard')).toBeInTheDocument()
  })

  it('sends a refused management user to the reports, their only page', () => {
    visit('/escalations', 'MANAGEMENT')
    expect(screen.getByText('page:reports')).toBeInTheDocument()
  })
})

describe('dashboard and redirects', () => {
  it('shows the dashboard to staff and admins', () => {
    for (const role of ['ICR', 'SUPERVISOR', 'ADMIN'] as const) {
      const { unmount } = visit('/dashboard', role)
      expect(screen.getByText('page:dashboard')).toBeInTheDocument()
      unmount()
    }
  })

  it('sends a management user from the dashboard to the reports', () => {
    visit('/dashboard', 'MANAGEMENT')
    expect(screen.getByText('page:reports')).toBeInTheDocument()
  })

  it('sends a signed-out visitor to login from any page', () => {
    for (const path of ['/dashboard', '/administration', '/reports']) {
      const { unmount } = visit(path, null)
      expect(screen.getByText('page:login')).toBeInTheDocument()
      unmount()
    }
  })

  it('sends the root and unknown addresses to the dashboard, or to login when signed out', () => {
    const signedIn = visit('/nowhere', 'ICR')
    expect(screen.getByText('page:dashboard')).toBeInTheDocument()
    signedIn.unmount()

    visit('/', null)
    expect(screen.getByText('page:login')).toBeInTheDocument()
  })

  it('sends an old call-history link to that call’s post-call analysis', () => {
    visit('/call-history?call_id=CALL-1', 'ICR')
    expect(screen.getByText('page:post-call')).toBeInTheDocument()
  })

  it('sends call history without a call to the dashboard', () => {
    visit('/call-history', 'ICR')
    expect(screen.getByText('page:dashboard')).toBeInTheDocument()
  })
})
