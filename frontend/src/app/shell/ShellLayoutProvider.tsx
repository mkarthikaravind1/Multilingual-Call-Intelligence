import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  DRAWER_MEDIA_QUERY,
  ShellLayoutContext,
  type ShellLayoutContextValue,
} from './shell-layout-context'

// Mounted above the routes so the sidebar state survives page navigation.
export function ShellLayoutProvider({ children }: { children: ReactNode }) {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)

  const closeDrawer = useCallback(() => setIsDrawerOpen(false), [])

  const toggleNavigation = useCallback(() => {
    if (window.matchMedia(DRAWER_MEDIA_QUERY).matches) {
      setIsDrawerOpen((open) => !open)
    } else {
      setIsSidebarCollapsed((collapsed) => !collapsed)
    }
  }, [])

  useEffect(() => {
    if (!isDrawerOpen) {
      return
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsDrawerOpen(false)
      }
    }

    // Leaving the drawer breakpoint (e.g. rotating a tablet) closes it.
    const mediaQuery = window.matchMedia(DRAWER_MEDIA_QUERY)
    const handleMediaChange = () => {
      if (!mediaQuery.matches) {
        setIsDrawerOpen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    mediaQuery.addEventListener('change', handleMediaChange)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      mediaQuery.removeEventListener('change', handleMediaChange)
    }
  }, [isDrawerOpen])

  const value = useMemo<ShellLayoutContextValue>(
    () => ({ isSidebarCollapsed, isDrawerOpen, toggleNavigation, closeDrawer }),
    [isSidebarCollapsed, isDrawerOpen, toggleNavigation, closeDrawer],
  )

  return <ShellLayoutContext.Provider value={value}>{children}</ShellLayoutContext.Provider>
}
