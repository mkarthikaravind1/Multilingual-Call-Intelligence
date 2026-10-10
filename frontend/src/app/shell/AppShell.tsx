import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'

import { ErrorBoundary } from '../components/ErrorBoundary'
import { SessionExpiryNotice } from './SessionExpiryNotice'
import { Sidebar } from './Sidebar'
import { TopHeader } from './TopHeader'
import { useShellLayout } from './useShellLayout'

type AppShellProps = {
  title: string
  subtitle?: string
  children: ReactNode
}

export function AppShell({ title, subtitle, children }: AppShellProps) {
  const { isDrawerOpen, closeDrawer } = useShellLayout()
  const { pathname } = useLocation()

  return (
    <div className="app-shell">
      <Sidebar />

      {isDrawerOpen && (
        <div className="app-shell__overlay" onClick={closeDrawer} aria-hidden="true" />
      )}

      <div className="app-shell__main">
        <TopHeader title={title} subtitle={subtitle} />
        <main className="app-shell__content">
          <SessionExpiryNotice />
          {/* A page that fails keeps the menu, so the user can go elsewhere;
              moving to another page clears the failure. */}
          <ErrorBoundary key={pathname}>{children}</ErrorBoundary>
        </main>
      </div>
    </div>
  )
}
