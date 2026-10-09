import { useAuth } from '../auth/useAuth'
import { decodeJwtClaims } from '../auth/session'
import { PostCallRepairPanel } from '../features/admin/components/PostCallRepairPanel'
import { UserManagementPanel } from '../features/admin/components/UserManagementPanel'

// Mirrors the permissions the application enforces today.
const ROLE_CAPABILITIES = [
  {
    role: 'ICR',
    description:
      'Handles calls: live call workspace, call history, post-call analysis, complaints and learning insights (read-only).',
  },
  {
    role: 'SUPERVISOR',
    description:
      'Everything an ICR can do, plus the escalation queue, reviewing AI improvements and emerging complaints, retrying post-call processing, and managing the price list.',
  },
  {
    role: 'ADMIN',
    description:
      'Everything a Supervisor can do except managing the price list, plus managing users and roles.',
  },
]

export function AdministrationPage() {
  const { session } = useAuth()
  const currentUserId = session ? (decodeJwtClaims(session.accessToken).sub ?? null) : null

  return (
    <section className="page-shell">
      <UserManagementPanel currentUserId={currentUserId} />

      <PostCallRepairPanel />

      <section className="panel">
        <h3 className="section-title">Roles</h3>
        <div className="card-stack">
          {ROLE_CAPABILITIES.map(({ role, description }) => (
            <article key={role} className="list-card">
              <div className="list-card__meta">
                <strong className="list-card__title">{role}</strong>
                {session?.role === role && <span className="badge badge--active">Your role</span>}
              </div>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>
    </section>
  )
}
