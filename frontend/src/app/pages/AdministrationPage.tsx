import { useEffect, useMemo, useState } from 'react'

import { ApiError } from '../api/errors'
import { useAuth } from '../auth/useAuth'
import { decodeJwtClaims } from '../auth/session'
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
    role: 'ADMIN',
    description:
      'Everything a Supervisor can do except managing the price list, plus managing users, roles and locations.',
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
