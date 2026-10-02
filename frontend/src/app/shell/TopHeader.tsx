import { useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'

import type { UserRole } from '../api/types/auth'
import { useAuth } from '../auth/useAuth'
import { NavIcon } from './NavIcon'
import { DRAWER_MEDIA_QUERY, SIDEBAR_ID } from './shell-layout-context'
import { useShellLayout } from './useShellLayout'

type TopHeaderProps = {
  title: string
  subtitle?: string
}

const ROLE_LABELS: Record<UserRole, string> = {
  ICR: 'ICR',
  SUPERVISOR: 'Supervisor',
  ADMIN: 'Admin',
}

function subscribeToDrawerLayout(onChange: () => void) {
  const query = window.matchMedia(DRAWER_MEDIA_QUERY)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

function isDrawerLayout() {
  return window.matchMedia(DRAWER_MEDIA_QUERY).matches
}

export function TopHeader({ title, subtitle }: TopHeaderProps) {
  const navigate = useNavigate()
  const { logout, session } = useAuth()
  const { isSidebarCollapsed, isDrawerOpen, toggleNavigation } = useShellLayout()
  const drawerLayout = useSyncExternalStore(subscribeToDrawerLayout, isDrawerLayout)

  const roleLabel = session?.role ? ROLE_LABELS[session.role] : null

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  // One control: collapses the sidebar on desktop, opens the drawer on
  // tablet/mobile (see ShellLayoutProvider). While the navigation is open it
  // shows a "collapse panel" icon; once folded away, the usual hamburger.
  const isNavigationOpen = drawerLayout ? isDrawerOpen : !isSidebarCollapsed
  const menuLabel = drawerLayout
    ? isDrawerOpen
      ? 'Close navigation'
      : 'Open navigation'
    : isSidebarCollapsed
      ? 'Expand navigation'
      : 'Collapse navigation'

  return (
    <header className="top-header">
      <div className="top-header__lead">
        <button
          type="button"
          className="top-header__menu"
          onClick={toggleNavigation}
          aria-label={menuLabel}
          title={menuLabel}
          aria-controls={SIDEBAR_ID}
          aria-expanded={isNavigationOpen}
        >
          <NavIcon name={isNavigationOpen ? 'collapse-panel' : 'menu'} />
        </button>

        <div className="top-header__copy">
          <h1 className="top-header__title">{title}</h1>
          {subtitle ? <p className="top-header__subtitle">{subtitle}</p> : null}
        </div>
      </div>

      <div className="top-header__actions" aria-label="Session controls">
        {roleLabel && (
          <>
            <span className="top-header__pill">{roleLabel}</span>
            <span
              className="top-header__avatar"
              role="img"
              aria-label={`Signed in as ${roleLabel}`}
              title={`Signed in as ${roleLabel}`}
            >
              {roleLabel.charAt(0)}
            </span>
          </>
        )}
        <button type="button" className="top-header__logout" onClick={handleLogout}>
          Logout
        </button>
      </div>
    </header>
  )
}
