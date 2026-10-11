import { useEffect, useState } from 'react'

import { ApiError } from '../api/errors'
import { useAuth } from '../auth/useAuth'
import { StatePanel } from '../components/StatePanel'
import { CallBrowser } from '../features/live-call/components/CallBrowser'
import { callRestService } from '../features/live-call/services/callRestService'
import type { CallStatsResponseDto } from '../features/live-call/types/dto'

export function DashboardPage() {
  // An admin reads the dashboard: the same counts and list, no way into a
  // call that is still in progress.
  const isAdmin = useAuth().session?.role === 'ADMIN'
  const [stats, setStats] = useState<CallStatsResponseDto | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    callRestService
      .getCallStats()
      .then((response) => {
        if (cancelled) return
        setStats(response)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Unable to load the call counts.')
      })

    return () => {
      cancelled = true
    }
  }, [])

  const metrics = [
    { label: 'Total calls', value: stats?.total, highlight: true },
    { label: 'Active calls', value: stats?.active },
    { label: 'Completed calls', value: stats?.completed },
  ]

  return (
    <section className="page-shell">
      {error && (
        <StatePanel variant="error" title="Could not load the call counts" description={error} />
      )}

      <div className="dashboard-stats">
        {metrics.map((metric) => (
          <div
            key={metric.label}
            className={`dashboard-stat${metric.highlight ? ' dashboard-stat--highlight' : ''}`}
          >
            <span>{metric.label}:</span>
            <strong>
              {stats ? metric.value : error ? '—' : <span className="spinner" aria-label="Loading" />}
            </strong>
          </div>
        ))}
      </div>

      <CallBrowser
        finishedCallsOnly={isAdmin}
        emptyState={
          <StatePanel
            title="No calls yet"
            description={
              isAdmin
                ? 'Calls appear here once executives take them.'
                : 'Start a call from Live Call or receive one through telephony to see it here.'
            }
            compact
          />
        }
      />
    </section>
  )
}
