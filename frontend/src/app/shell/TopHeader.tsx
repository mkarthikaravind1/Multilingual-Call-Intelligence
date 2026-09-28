import { useNavigate } from 'react-router-dom'

import type { UserRole } from '../api/types/auth'
import { useAuth } from '../auth/useAuth'
import { NavIcon } from './NavIcon'
import { SIDEBAR_ID } from './shell-layout-context'
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

export function TopHeader({ title, subtitle }: TopHeaderProps) {
  const navigate = useNavigate()
  const { logout, session } = useAuth()
  const { isSidebarCollapsed, isDrawerOpen, toggleNavigation } = useShellLayout()

  const roleLabel = session?.role ? ROLE_LABELS[session.role] : null

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  // One control: collapses the sidebar on desktop, opens the drawer on
  // tablet/mobile (see ShellLayoutProvider).
  const menuLabel = isDrawerOpen
    ? 'Close navigation'
    : isSidebarCollapsed
      ? 'Expand navigation'
      : 'Toggle navigation'

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
          aria-expanded={isDrawerOpen || !isSidebarCollapsed}
        >
          <NavIcon name="menu" />
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
