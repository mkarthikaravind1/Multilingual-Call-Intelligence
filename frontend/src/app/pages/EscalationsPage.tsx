import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { toEscalationViewModel } from '../features/escalation/adapters/toEscalationViewModel'
import { EscalationCard } from '../features/escalation/components/EscalationCard'
import { escalationRestService } from '../features/escalation/services/escalationRestService'

import type {
  EscalationQueueFilters,
  EscalationQueueState,
  EscalationStatsDto,
} from '../features/escalation/types/dto'
import type { EscalationViewModel } from '../features/escalation/types/view-models'

// New escalations appear without a manual refresh.
const REFRESH_INTERVAL_MS = 10000

type QueueView = Exclude<EscalationQueueState, 'active'>

const VIEWS: { value: QueueView; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All' },
]

const EMPTY_MESSAGES: Record<QueueView, { title: string; description: string }> = {
  open: {
    title: 'No open escalations',
    description:
      'Calls appear here as soon as a customer asks for a manager, threatens legal action or a public complaint, wants to cancel, or stays clearly negative with open complaints.',
  },
  acknowledged: {
    title: 'No acknowledged escalations',
    description: 'Escalations a supervisor has acknowledged but not resolved yet appear here.',
  },
  resolved: {
    title: 'No resolved escalations yet',
    description: 'Escalations you resolve are kept here with the resolution note.',
  },
  all: {
    title: 'No escalations yet',
    description: 'Every escalated call is listed here, open ones first.',
  },
}

type DateRanges = {
  detectedFrom: string
  detectedTo: string
  acknowledgedFrom: string
  acknowledgedTo: string
}

const NO_DATES: DateRanges = {
  detectedFrom: '',
  detectedTo: '',
  acknowledgedFrom: '',
  acknowledgedTo: '',
}

// <input type="date"> values are local calendar days; the API takes epoch
// seconds, from inclusive and to exclusive (so "to" is the next midnight).
function localMidnight(day: string, addDays = 0): number | undefined {
  const [year, month, date] = day.split('-').map(Number)
  if (!year || !month || !date) return undefined
  return new Date(year, month - 1, date + addDays).getTime() / 1000
}

function toFilters(dates: DateRanges): EscalationQueueFilters {
  return {
    detectedFrom: localMidnight(dates.detectedFrom),
    detectedTo: localMidnight(dates.detectedTo, 1),
    acknowledgedFrom: localMidnight(dates.acknowledgedFrom),
    acknowledgedTo: localMidnight(dates.acknowledgedTo, 1),
  }
}

export function EscalationsPage() {
  const [view, setView] = useState<QueueView>('all')
  const [dates, setDates] = useState<DateRanges>(NO_DATES)
  const [escalations, setEscalations] = useState<EscalationViewModel[]>([])
  const [stats, setStats] = useState<EscalationStatsDto | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadCount, setReloadCount] = useState(0)

  const dateKey = JSON.stringify(dates)
  const hasDates = Object.values(dates).some(Boolean)

  const load = useCallback(async (state: QueueView, filters: EscalationQueueFilters) => {
    try {
      const [data, counts] = await Promise.all([
        escalationRestService.listQueue(state, filters),
        escalationRestService.getStats(),
      ])
      setEscalations(data.map(toEscalationViewModel))
      setStats(counts)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to load escalations.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const filters = toFilters(JSON.parse(dateKey) as DateRanges)
    const refresh = () => {
      if (!cancelled) {
        void load(view, filters)
      }
    }
    refresh()
    const intervalId = window.setInterval(refresh, REFRESH_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [view, dateKey, load, reloadCount])

  // Every filter change shows a fresh list rather than the previous one.
  const changeFilters = (apply: () => void) => {
    setIsLoading(true)
    setEscalations([])
    apply()
  }

  const setDate = (name: keyof DateRanges, value: string) =>
    changeFilters(() => setDates((current) => ({ ...current, [name]: value })))

  // An update may move the escalation out of the current view, and changes
  // the totals, so both are fetched again.
  const handleUpdated = (updated: EscalationViewModel) => {
    setEscalations((current) =>
      current.map((item) => (item.callId === updated.callId ? updated : item)),
    )
    setReloadCount((count) => count + 1)
  }

  const metrics = [
    { label: 'Active', value: stats?.active, highlight: true },
    { label: 'Critical', value: stats?.critical },
    { label: 'Not yet acknowledged', value: stats?.unacknowledged },
  ]

  const dateRange = (
    title: string,
    from: keyof DateRanges,
    to: keyof DateRanges,
  ) => (
    <fieldset className="call-filters__range">
      <legend>{title}</legend>
      <label className="call-filters__date">
        <span>From</span>
        <input
          type="date"
          value={dates[from]}
          max={dates[to] || undefined}
          onChange={(event) => setDate(from, event.target.value)}
        />
      </label>
      <label className="call-filters__date">
        <span>To</span>
        <input
          type="date"
          value={dates[to]}
          min={dates[from] || undefined}
          onChange={(event) => setDate(to, event.target.value)}
        />
      </label>
      {dates[from] && dates[to] && dates[from] > dates[to] && (
        <span className="call-filters__hint" role="alert">
          “From” is after “To”.
        </span>
      )}
    </fieldset>
  )

  return (
    <section className="page-shell">
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

      <div className="panel call-filters" role="search" aria-label="Filter escalations">
        <div className="call-filters__row">
          <fieldset className="call-filters__checks">
            <legend>Show</legend>
            {VIEWS.map((item) => (
              <label key={item.value} className="call-filters__check">
                <input
                  type="radio"
                  name="escalation-view"
                  value={item.value}
                  checked={view === item.value}
                  onChange={() => changeFilters(() => setView(item.value))}
                />
                {item.label}
              </label>
            ))}
          </fieldset>
        </div>

        <div className="call-filters__row">
          {dateRange('Detected date', 'detectedFrom', 'detectedTo')}
          {dateRange('Acknowledged date', 'acknowledgedFrom', 'acknowledgedTo')}
          <div className="call-filters__actions">
            <button
              type="button"
              className="button button--secondary"
              disabled={!hasDates}
              onClick={() => changeFilters(() => setDates(NO_DATES))}
            >
              Clear dates
            </button>
          </div>
        </div>
      </div>

      {isLoading && <StatePanel variant="loading" title="Loading escalations…" />}

      {!isLoading && error && (
        <StatePanel variant="error" title="Could not load escalations" description={error} />
      )}

      {!isLoading && !error && escalations.length === 0 && (
        <StatePanel
          title={hasDates ? 'No escalations in these dates' : EMPTY_MESSAGES[view].title}
          description={
            hasDates
              ? 'Try a wider date range, or clear the dates. An acknowledged-date range only matches escalations that were acknowledged.'
              : EMPTY_MESSAGES[view].description
          }
        />
      )}

      {!isLoading && !error && escalations.length > 0 && (
        <div className="card-stack">
          {escalations.map((escalation) => (
            <EscalationCard
              key={escalation.callId}
              escalation={escalation}
              canManage
              showCallLink
              onUpdated={handleUpdated}
            />
          ))}
        </div>
      )}
    </section>
  )
}
