import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { useAuth } from '../auth/useAuth'
import { decodeJwtClaims } from '../auth/session'
import { ComplaintCategoriesPanel } from '../features/admin/components/ComplaintCategoriesPanel'
import { DataSafetyPanel } from '../features/admin/components/DataSafetyPanel'
import { LocationsPanel } from '../features/admin/components/LocationsPanel'
import { PostCallRepairPanel } from '../features/admin/components/PostCallRepairPanel'
import { ReportLayoutPanel } from '../features/admin/components/ReportLayoutPanel'
import { TrainingDataPanel } from '../features/admin/components/TrainingDataPanel'
import { UserManagementPanel } from '../features/admin/components/UserManagementPanel'
import { adminRestService } from '../features/admin/services/adminRestService'
import type { LocationDto, ManagedUserDto } from '../features/admin/types/dto'

// Mirrors the permissions the application enforces today.
const ROLE_CAPABILITIES = [
  {
    role: 'ICR',
    description:
      'Takes calls: the dashboard, the live call workspace, post-call analysis, complaints, and the AI Improvement Center (read-only). Starts, holds and completes calls, records the customer and vehicle, updates complaints and corrects the AI on a call.',
  },
  {
    role: 'SUPERVISOR',
    description:
      'Everything an ICR can do, plus the live calls view, the escalation queue (acknowledge and resolve), reports, the price list, reviewing AI improvements and emerging complaint themes, call recordings, test audio, and retrying post-call processing.',
  },
  {
    role: 'ADMIN',
    description:
      'Sets up and maintains the system: users, locations, complaint categories, the report layout, data safety, the post-call repair list, the training data download, the audit log and the AI log. Reads the reports and the dashboard, and can open a call once it has ended (transcript, summary, audit score). Takes no calls, handles no complaints or escalations and cannot listen to recordings.',
  },
  {
    role: 'MANAGEMENT',
    description:
      'Reads the reports and performance figures, with their exports, and can open a finished call from a report (transcript, summary, audit score). Sees no live calls, changes nothing and takes no calls.',
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
      // Only those who take calls belong to a location.
      if (user.location_id && (user.role === 'ICR' || user.role === 'SUPERVISOR')) {
        counts[user.location_id] = (counts[user.location_id] ?? 0) + 1
      }
    }
    return counts
  }, [users])

  // The first account is an admin, who takes no calls: until a supervisor
  // exists nobody can watch calls, handle escalations or keep the price list.
  const needsSupervisor =
    users.length > 0 && !users.some((user) => user.role === 'SUPERVISOR' && user.is_active)

  return (
    <section className="page-shell">
      {needsSupervisor && (
        <p className="inline-notice" role="status">
          <strong>No active Supervisor yet.</strong> An Admin sets the system up but takes no
          calls. Create a Supervisor under Users before calls can be taken or watched: the
          Supervisor looks after live calls, escalations, the price list and call recordings, and
          the executives (ICR) answer the calls.
        </p>
      )}

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

      <ReportLayoutPanel />

      <DataSafetyPanel />

      <TrainingDataPanel />

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
