import { IntegrationPendingCard } from '../components/IntegrationPendingCard'
import { useAuth } from '../auth/useAuth'

// Mirrors the permissions the application enforces today.
const ROLE_CAPABILITIES = [
  {
    role: 'ICR',
    description: 'Handles calls: live call workspace, call history, post-call analysis and learning insights (read-only).',
  },
  {
    role: 'SUPERVISOR',
    description: 'Everything an ICR can do, plus approving or rejecting AI improvement candidates.',
  },
  {
    role: 'ADMIN',
    description: 'Everything a Supervisor can do, plus access to administration.',
  },
]

export function AdministrationPage() {
  const { session } = useAuth()

  return (
    <section className="page-shell">
      <div className="page-shell__grid page-shell__grid--wide">
        <section className="panel">
          <h3 className="section-title">Roles</h3>
          <div className="card-stack">
            {ROLE_CAPABILITIES.map(({ role, description }) => (
              <article key={role} className="list-card">
                <div className="list-card__meta">
                  <strong className="list-card__title">{role}</strong>
                  {session?.role === role && (
                    <span className="badge badge--active">Your role</span>
                  )}
                </div>
                <p>{description}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <h3 className="section-title">User management</h3>
          <IntegrationPendingCard
            title="Users and invitations"
            description="Creating users, assigning roles and deactivating accounts will be available here once the user-management API is added to the backend."
          />
        </section>
      </div>
    </section>
  )
}
