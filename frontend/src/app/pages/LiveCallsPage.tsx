import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { ComplaintStatusBadge } from '../components/ToneBadges'
import { EscalationLevelBadge } from '../features/escalation/components/EscalationCard'
import { formatCallDirection } from '../features/live-call/adapters/toViewModel'
import { useCallDirectory } from '../features/live-call/hooks/useCallDirectory'
import { callRestService } from '../features/live-call/services/callRestService'
import type {
  CallDirectoryEntryDto,
  LiveCallDto,
  LiveCallsDto,
  LiveCallsFilters,
} from '../features/live-call/types/dto'
import { humanizeLabel } from '../format/text'
import { formatElapsedSeconds } from '../format/time'
import { LINE_TONES, lineToneKey } from '../format/tone'

const REFRESH_MS = 5000
// Calls on a page: the server orders them most urgent first.
const PAGE_SIZE = 50
const NO_FILTERS: LiveCallsFilters = {}

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

function hasFilters(filters: LiveCallsFilters) {
  return Boolean(
    filters.locationId || filters.executiveUserId || filters.sentiment || filters.alertsOnly,
  )
}

// Every call in progress at a glance, for supervisors. Refreshes by itself.
// Built for hundreds of calls at once: the server filters, orders (most
// urgent first) and pages them, and the totals cover every call.
export function LiveCallsPage() {
  const directory = useCallDirectory()
  const [filters, setFilters] = useState<LiveCallsFilters>(NO_FILTERS)
  const [offset, setOffset] = useState(0)
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  // Only the latest request's answer is shown: an earlier one can arrive
  // late after the filters or the page changed.
  const latestRequest = useRef(0)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      const request = ++latestRequest.current
      const isCurrent = () => !cancelled && request === latestRequest.current
      callRestService
        .getLiveCalls(PAGE_SIZE, offset, filters)
        .then((calls) => {
          if (!isCurrent()) return
          setLoaded({ calls, error: null })
          // Calls ended while a later page was open: go back to the last one.
          if (calls.items.length === 0 && offset > 0 && offset >= calls.matching) {
            setOffset(Math.max(0, Math.floor((calls.matching - 1) / PAGE_SIZE) * PAGE_SIZE))
          }
        })
        .catch((err) => {
          if (!isCurrent()) return
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
  }, [filters, offset])

  // Changes a filter and goes back to the first page.
  const updateFilters = (changes: Partial<LiveCallsFilters>) => {
    setFilters((current) => ({ ...current, ...changes }))
    setOffset(0)
  }

  if (!loaded) {
    return (
      <section className="page-shell">
        <StatePanel variant="loading" title="Loading live calls…" compact />
      </section>
    )
  }

  const calls = loaded.calls
  const filtered = hasFilters(filters)

  const choice = (
    label: string,
    value: string | undefined,
    options: ReadonlyArray<Pick<CallDirectoryEntryDto, 'id' | 'name'> & { is_active?: boolean }>,
    onChange: (value: string | undefined) => void,
  ) => (
    <label className="call-filters__choice">
      <span>{label}</span>
      <select value={value ?? ''} onChange={(event) => onChange(event.target.value || undefined)}>
        <option value="">All</option>
        {options
          .filter((option) => option.is_active !== false || option.id === value)
          .map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
      </select>
    </label>
  )

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
              <strong>{calls.with_alerts}</strong>
            </div>
            <div className="report-tile">
              <span>Negative tone</span>
              <strong>{calls.negative_tone}</strong>
            </div>
            <div className="report-tile">
              <span>Escalated</span>
              <strong>{calls.escalated}</strong>
            </div>
          </div>

          <div className="panel call-filters" role="search" aria-label="Filter live calls">
            <div className="call-filters__row">
              {choice('Location', filters.locationId, directory.locations, (locationId) =>
                updateFilters({ locationId }),
              )}
              {choice('Executive', filters.executiveUserId, directory.executives, (id) =>
                updateFilters({ executiveUserId: id }),
              )}
              {choice(
                'Tone',
                filters.sentiment,
                LINE_TONES.map((tone) => ({ id: tone.toUpperCase(), name: humanizeLabel(tone) })),
                (sentiment) => updateFilters({ sentiment }),
              )}
              <label className="call-filters__check">
                <input
                  type="checkbox"
                  checked={filters.alertsOnly ?? false}
                  onChange={(event) => updateFilters({ alertsOnly: event.target.checked })}
                />
                Only calls with an alert
              </label>
              <div className="call-filters__actions">
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => {
                    setFilters(NO_FILTERS)
                    setOffset(0)
                  }}
                  disabled={!filtered}
                >
                  Clear filters
                </button>
              </div>
            </div>
          </div>

          {calls.items.length === 0 ? (
            <StatePanel
              title={filtered ? 'No live calls match these filters' : 'No calls in progress'}
              description={
                filtered
                  ? 'Calls that come to match appear here by themselves.'
                  : 'Calls appear here as soon as they start. This page refreshes by itself.'
              }
              compact
            />
          ) : (
            <>
              {/* The server sends them most urgent first. */}
              <div className="live-cards">
                {calls.items.map((call) => (
                  <LiveCallCard key={call.call_id} call={call} now={calls.now} />
                ))}
              </div>
              <div className="pager">
                <span>
                  Showing <strong>{calls.offset + 1}–{calls.offset + calls.items.length}</strong>{' '}
                  of <strong>{calls.matching}</strong> {filtered ? 'matching calls' : 'calls'},
                  most urgent first
                </span>
                {calls.matching > PAGE_SIZE && (
                  <div className="button-row">
                    <button
                      type="button"
                      className="button button--secondary"
                      onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                      disabled={offset === 0}
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      className="button button--secondary"
                      onClick={() => setOffset(offset + PAGE_SIZE)}
                      disabled={calls.offset + calls.items.length >= calls.matching}
                    >
                      Next
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
        </>
      )}
    </section>
  )
}
