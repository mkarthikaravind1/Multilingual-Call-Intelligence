import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { toCallMetadataViewModel } from '../features/live-call/adapters/toViewModel'
import { CallTable } from '../features/live-call/components/CallTable'
import { callRestService } from '../features/live-call/services/callRestService'
import type { CallStatsResponseDto } from '../features/live-call/types/dto'
import type { CallMetadataViewModel } from '../features/live-call/types/view-models'

const RECENT_CALL_COUNT = 5

type DashboardData = {
  stats: CallStatsResponseDto
  recentCalls: CallMetadataViewModel[]
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    Promise.all([
      callRestService.getCallStats(),
      callRestService.listCalls(RECENT_CALL_COUNT, 0),
    ])
      .then(([stats, recent]) => {
        if (cancelled) return
        setData({
          stats,
          recentCalls: recent.items.map(toCallMetadataViewModel),
        })
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Unable to load the dashboard.')
      })

    return () => {
      cancelled = true
    }
  }, [])

  const metrics = [
    { label: 'Total calls', value: data?.stats.total, caption: 'All recorded calls', highlight: true },
    { label: 'Active calls', value: data?.stats.active, caption: 'Calls currently in progress' },
    { label: 'Completed calls', value: data?.stats.completed, caption: 'Calls that have ended' },
  ]

  return (
    <section className="page-shell">
      <div className="page-shell__header page-shell__header--actions">
        <div className="button-row">
          <Link className="button" to="/live-call">
            Open Live Call
          </Link>
          <Link className="button button--secondary" to="/call-history">
            View call history
          </Link>
        </div>
      </div>

      {error && (
        <StatePanel variant="error" title="Could not load the dashboard" description={error} />
      )}

      <div className="kpi-grid">
        {metrics.map((metric) => (
          <article
            key={metric.label}
            className={metric.highlight ? 'panel panel--highlight' : 'panel'}
          >
            <p className="panel__label">{metric.label}</p>
            <h3>{data ? metric.value : error ? '—' : <span className="spinner" aria-label="Loading" />}</h3>
            <span>{metric.caption}</span>
          </article>
        ))}
      </div>

      {!error && (
        <section>
          <div className="section-heading">
            <h3 className="section-title">Recent calls</h3>
            <Link className="text-link" to="/call-history">
              See all calls
            </Link>
          </div>

          {!data ? (
            <StatePanel variant="loading" title="Loading recent calls…" compact />
          ) : data.recentCalls.length === 0 ? (
            <StatePanel
              title="No calls yet"
              description="Start a call from Live Call or receive one through telephony to see it here."
              compact
            />
          ) : (
            <CallTable calls={data.recentCalls} />
          )}
        </section>
      )}
    </section>
  )
}
