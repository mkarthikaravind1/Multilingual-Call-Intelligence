import type { ReactNode } from 'react'

import { Sidebar } from './Sidebar'
import { TopHeader } from './TopHeader'

type AppShellProps = {
  title: string
  subtitle?: string
  children: ReactNode
}

export function AppShell({ title, subtitle, children }: AppShellProps) {
  return (
    <div className="app-shell">
      <Sidebar />

      <div className="app-shell__main">
        <TopHeader title={title} subtitle={subtitle} />
        <main className="app-shell__content">{children}</main>
      </div>
    </div>
  )
}
