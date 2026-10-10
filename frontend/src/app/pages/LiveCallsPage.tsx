import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { ComplaintStatusBadge } from '../components/ToneBadges'
import { EscalationLevelBadge } from '../features/escalation/components/EscalationCard'
import { formatCallDirection } from '../features/live-call/adapters/toViewModel'
import { callRestService } from '../features/live-call/services/callRestService'
import type { LiveCallDto, LiveCallsDto } from '../features/live-call/types/dto'
import { humanizeLabel } from '../format/text'
import { formatElapsedSeconds } from '../format/time'
import { lineToneKey } from '../format/tone'

const REFRESH_MS = 5000

type Loaded = { calls: LiveCallsDto | null; error: string | null }

function LiveCallCard({ call, now }: { call: LiveCallDto; now: number }) {
  const tone = lineToneKey(call.sentiment)
  const who = call.customer_name ?? call.caller_number ?? 'Unknown caller'
  const where = [formatCallDirection(call.direction), call.location_name]
    .filter(Boolean)
    .join(' · ')
  return (
    <article className={`live-card${call.alerts.length > 0 ? ' live-card--alert' : ''}`}>
      <header className="live-card__header">
        <div>
          <strong className="live-card__executive">
            {call.executive_name ?? 'Executive not recorded'}
          </strong>
          <span className="live-card__meta">{where || 'Location not recorded'}</span>
        </div>
        <span className="live-card__duration" title="Time on the call">
          {formatElapsedSeconds(now - call.start_time)}
        </span>
      </header>

      <p className="live-card__customer">
        With <strong>{who}</strong> · {call.utterance_count} lines
      </p>

      <div className="live-card__row">
        <span className="live-card__label">Tone</span>
        {tone ? (
          <span className="live-call__turn-tone">
            <span className={`tone-dot tone-dot--${tone}`} aria-hidden="true" />
            {humanizeLabel(tone)}
          </span>
        ) : (
          <span className="customer-panel__muted">Not analysed yet</span>
        )}
        {call.escalation_level && call.escalation_status !== 'resolved' && (
          <EscalationLevelBadge level={call.escalation_level} />
        )}
      </div>

      <div className="live-card__row live-card__row--wrap">
        <span className="live-card__label">Complaints</span>
        {call.complaints.length === 0 ? (
          <span className="customer-panel__muted">None so far</span>
        ) : (
          call.complaints.map((complaint) => (
            <span className="live-card__complaint" key={complaint.category}>
              {complaint.category}
              <ComplaintStatusBadge status={complaint.status} />
            </span>
          ))
        )}
      </div>

      {call.alerts.length > 0 && (
        <ul className="call-alerts__list">
          {call.alerts.map((alert) => (
            <li
              key={`${alert.alert_type}-${alert.subject}`}
              className={`call-alerts__item call-alerts__item--${alert.alert_type}`}
            >
              <strong>{humanizeLabel(alert.alert_type)}</strong>
              <span>{alert.message}</span>
            </li>
          ))}
        </ul>
      )}

      <Link
        className="call-history__link"
        to={`/live-call?call_id=${encodeURIComponent(call.call_id)}`}
      >
        Open the call
      </Link>
    </article>
  )
}

// Every active call at a glance, for supervisors. Refreshes by itself.
export function LiveCallsPage() {
  const [loaded, setLoaded] = useState<Loaded | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      callRestService
        .getLiveCalls()
        .then((calls) => {
          if (!cancelled) setLoaded({ calls, error: null })
        })
        .catch((err) => {
          if (cancelled) return
          // Keep showing the last list; say that it is no longer fresh.
          setLoaded((current) => ({
            calls: current?.calls ?? null,
            error: err instanceof ApiError ? err.message : 'Unable to load the live calls.',
          }))
        })
    }
    load()
    const timer = window.setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  if (!loaded) {
    return (
      <section className="page-shell">
        <StatePanel variant="loading" title="Loading live calls…" compact />
      </section>
    )
  }

  const calls = loaded.calls
  const withAlerts = calls?.items.filter((call) => call.alerts.length > 0).length ?? 0

  return (
    <section className="page-shell">
      {loaded.error && (
        <p className="review-form__error" role="alert">
          {calls ? `Not refreshing: ${loaded.error}` : loaded.error}
        </p>
      )}

      {calls && (
        <>
          <div className="report-tiles">
            <div className="report-tile">
              <span>Active calls</span>
              <strong>{calls.total}</strong>
            </div>
            <div className="report-tile">
              <span>With an alert</span>
              <strong>{withAlerts}</strong>
            </div>
          </div>

          {calls.total > calls.items.length && (
            <p className="inline-notice">
              Showing the {calls.items.length} most recent of {calls.total} active calls.
            </p>
          )}

          {calls.items.length === 0 ? (
            <StatePanel
              title="No calls in progress"
              description="Calls appear here as soon as they start. This page refreshes by itself."
              compact
            />
          ) : (
            <div className="live-cards">
              {/* Calls that need attention first. */}
              {[...calls.items]
                .sort((a, b) => b.alerts.length - a.alerts.length)
                .map((call) => (
                  <LiveCallCard key={call.call_id} call={call} now={calls.now} />
                ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
