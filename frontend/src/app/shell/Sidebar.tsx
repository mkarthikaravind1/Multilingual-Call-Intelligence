import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/live-call', label: 'Live Call' },
  { to: '/call-history', label: 'Call History' },
  { to: '/post-call-analysis', label: 'Post-call Analysis' },
  { to: '/ai-improvement', label: 'AI Improvement Center' },
]

export function Sidebar() {
  return (
    <aside className="sidebar" aria-label="Sidebar navigation">
      <div className="sidebar__brand" aria-label="Application brand">
        <div className="sidebar__brand-mark" aria-hidden="true">
          M
        </div>
        <div className="sidebar__brand-copy">
          <span className="sidebar__brand-name">Multilingual</span>
          <span className="sidebar__brand-subtitle">Customer Intelligence</span>
        </div>
      </div>

      <nav className="sidebar__nav" aria-label="Main navigation">
        {navItems.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              ['sidebar__nav-item', isActive ? 'sidebar__nav-item--active' : ''].join(' ')
            }
            end={to === '/dashboard'}
          >
            <span className="sidebar__nav-label">{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
