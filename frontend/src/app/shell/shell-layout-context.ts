import { createContext } from 'react'

export interface ShellLayoutContextValue {
  // Desktop: sidebar reduced to icons. Mobile/tablet: ignored.
  isSidebarCollapsed: boolean
  // Mobile/tablet: navigation drawer shown over the content.
  isDrawerOpen: boolean
  toggleNavigation: () => void
  closeDrawer: () => void
}

export const ShellLayoutContext = createContext<ShellLayoutContextValue | null>(null)

export const SIDEBAR_ID = 'app-sidebar'

// Must match the drawer breakpoint in app-shell.css.
export const DRAWER_MEDIA_QUERY = '(max-width: 980px)'
