import type { ReactNode } from 'react'

type MainContentProps = {
  children: ReactNode
}

export function MainContent({ children }: MainContentProps) {
  return <div className="main-content">{children}</div>
}
