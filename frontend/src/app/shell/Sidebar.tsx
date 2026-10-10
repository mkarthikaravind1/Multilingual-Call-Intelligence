import { NavLink } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'
import { NavIcon, type NavIconName } from './NavIcon'
import { SIDEBAR_ID } from './shell-layout-context'
import { useShellLayout } from './useShellLayout'

type NavItem = { to: string; label: string; icon: NavIconName }

const navItems: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: 'dashboard' },
  { to: '/live-call', label: 'Live Call', icon: 'live-call' },
  { to: '/complaints', label: 'Complaints', icon: 'complaints' },
  { to: '/ai-improvement', label: 'AI Improvement Center', icon: 'ai-improvement' },
]

const supervisorNavItems: NavItem[] = [
  { to: '/escalations', label: 'Escalations', icon: 'escalations' },
  { to: '/reports', label: 'Reports', icon: 'reports' },
]

// Supervisors only, not admins.
const supervisorRoleNavItems: NavItem[] = [
  { to: '/price-list', label: 'Price List', icon: 'price-list' },
]

const adminNavItems: NavItem[] = [
  { to: '/administration', label: 'Administration', icon: 'administration' },
]

export function Sidebar() {
  const { session } = useAuth()
  const { isSidebarCollapsed, isDrawerOpen, closeDrawer } = useShellLayout()
  const visibleItems = [
    ...navItems,
    ...(session?.role === 'SUPERVISOR' || session?.role === 'ADMIN' ? supervisorNavItems : []),
    ...(session?.role === 'SUPERVISOR' ? supervisorRoleNavItems : []),
    ...(session?.role === 'ADMIN' ? adminNavItems : []),
  ]

  const className = [
    'sidebar',
    isSidebarCollapsed ? 'sidebar--collapsed' : '',
    isDrawerOpen ? 'sidebar--drawer-open' : '',
  ].join(' ')

  return (
    <aside id={SIDEBAR_ID} className={className} aria-label="Sidebar navigation">
      <div className="sidebar__brand" aria-label="Application brand">
        <div className="sidebar__brand-mark" aria-hidden="true">
          <NavIcon name="brand" />
        </div>
        <div className="sidebar__brand-copy">
          <span className="sidebar__brand-name">Multilingual</span>
          <span className="sidebar__brand-subtitle">Call Intelligence</span>
        </div>
        <button
          type="button"
          className="sidebar__close"
          onClick={closeDrawer}
          aria-label="Close navigation"
        >
          <NavIcon name="close" />
        </button>
      </div>

      <nav className="sidebar__nav" aria-label="Main navigation">
        {visibleItems.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              ['sidebar__nav-item', isActive ? 'sidebar__nav-item--active' : ''].join(' ')
            }
            end={to === '/dashboard'}
            title={isSidebarCollapsed ? label : undefined}
            aria-label={isSidebarCollapsed ? label : undefined}
            onClick={closeDrawer}
          >
            <NavIcon name={icon} />
            <span className="sidebar__nav-label">{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
