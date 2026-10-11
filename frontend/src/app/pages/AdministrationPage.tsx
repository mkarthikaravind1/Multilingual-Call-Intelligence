import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { useAuth } from '../auth/useAuth'
import { decodeJwtClaims } from '../auth/session'
import { ComplaintCategoriesPanel } from '../features/admin/components/ComplaintCategoriesPanel'
import { DataSafetyPanel } from '../features/admin/components/DataSafetyPanel'
import { LocationsPanel } from '../features/admin/components/LocationsPanel'
import { PostCallRepairPanel } from '../features/admin/components/PostCallRepairPanel'
import { UserManagementPanel } from '../features/admin/components/UserManagementPanel'
import { adminRestService } from '../features/admin/services/adminRestService'
import type { LocationDto, ManagedUserDto } from '../features/admin/types/dto'

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
      'Everything an ICR can do, plus the escalation queue, reports, reviewing AI improvements and emerging complaints, retrying post-call processing, and managing the price list.',
  },
  {
    role: 'MANAGEMENT',
    description:
      'Reads the reports and performance figures, with their exports, and can open a finished call from a report (transcript, summary, audit score). Sees no live calls, changes nothing and takes no calls.',
  },
  {
    role: 'ADMIN',
    description:
      'Everything a Supervisor can do except managing the price list, plus managing users, roles, locations and complaint categories, and reading the audit log and the AI log.',
  },
]

export function AdministrationPage() {
  const { session } = useAuth()
  const currentUserId = session ? (decodeJwtClaims(session.accessToken).sub ?? null) : null

  // Shared by the two panels: users choose from the locations, and each
  // location shows how many users it has.
  const [locations, setLocations] = useState<LocationDto[]>([])
  const [locationsLoading, setLocationsLoading] = useState(true)
  const [locationsError, setLocationsError] = useState<string | null>(null)
  const [users, setUsers] = useState<ManagedUserDto[]>([])

  useEffect(() => {
    let cancelled = false
    adminRestService
      .listLocations()
      .then((loaded) => {
        if (cancelled) return
        setLocations(loaded)
        setLocationsError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setLocationsError(err instanceof ApiError ? err.message : 'Unable to load locations.')
      })
      .finally(() => {
        if (!cancelled) setLocationsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const userCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const user of users) {
      if (user.location_id) counts[user.location_id] = (counts[user.location_id] ?? 0) + 1
    }
    return counts
  }, [users])

  return (
    <section className="page-shell">
      <LocationsPanel
        locations={locations}
        isLoading={locationsLoading}
        loadError={locationsError}
        userCounts={userCounts}
        onChanged={setLocations}
      />

      <UserManagementPanel
        currentUserId={currentUserId}
        locations={locations}
        onUsersChanged={setUsers}
      />

      <ComplaintCategoriesPanel />

      <PostCallRepairPanel />

      <DataSafetyPanel />

      <section className="panel">
        <h3 className="section-title">Logs</h3>
        <div className="card-stack">
          <article className="list-card">
            <Link className="text-link list-card__title" to="/administration/audit-log">
              Audit log
            </Link>
            <p>
              Who did what, and when: every change, sign-ins, recordings listened to and
              downloads.
            </p>
          </article>
          <article className="list-card">
            <Link className="text-link list-card__title" to="/administration/ai-log">
              AI log
            </Link>
            <p>What the AI was asked and what it answered for each call, with token counts.</p>
          </article>
        </div>
      </section>

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
