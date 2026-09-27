import { useEffect, useState } from 'react'

import { ApiError } from '../api/errors'
import { callRestService } from '../features/live-call/services/callRestService'
import type { CallStatsResponseDto } from '../features/live-call/types/dto'

export function DashboardPage() {
  const [stats, setStats] = useState<CallStatsResponseDto | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    callRestService
      .getCallStats()
      .then((response) => {
        if (!cancelled) setStats(response)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Unable to load call statistics.')
      })

    return () => {
      cancelled = true
    }
  }, [])

  const display = (value: number | undefined) =>
    stats ? String(value) : error ? '—' : '…'

  return (
    <section className="page-shell">
      <div className="page-shell__header">
        <div>
          <p className="eyebrow">Operations</p>
          <h2>Customer intelligence overview</h2>
        </div>
      </div>

      {error && (
        <div className="live-call__error" role="alert">
          <strong>Could not load call statistics</strong>
          <span>{error}</span>
        </div>
      )}

      <div className="page-shell__grid">
        <article className="panel panel--highlight">
          <p className="panel__label">Total calls</p>
          <h3>{display(stats?.total)}</h3>
          <span>All recorded calls</span>
        </article>
        <article className="panel">
          <p className="panel__label">Active calls</p>
          <h3>{display(stats?.active)}</h3>
          <span>Calls currently in progress</span>
        </article>
        <article className="panel">
          <p className="panel__label">Completed calls</p>
          <h3>{display(stats?.completed)}</h3>
          <span>Calls that have ended</span>
        </article>
      </div>
    </section>
  )
}
