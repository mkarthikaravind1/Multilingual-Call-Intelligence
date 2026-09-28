import type { ReactNode } from 'react'

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

  return (
    <div className="app-shell">
      <Sidebar />

      {isDrawerOpen && (
        <div className="app-shell__overlay" onClick={closeDrawer} aria-hidden="true" />
      )}

      <div className="app-shell__main">
        <TopHeader title={title} subtitle={subtitle} />
        <main className="app-shell__content">{children}</main>
      </div>
    </div>
  )
}
