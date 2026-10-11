import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { RecordTime } from '../components/RecordTime'
import { StatePanel } from '../components/StatePanel'
import { LogPager } from '../features/admin/components/LogPager'
import { LOG_PAGE_SIZE, localMidnight, withFilter } from '../features/admin/logFilters'
import { logRestService } from '../features/admin/services/logRestService'
import type { AuditEntryDto, AuditLogDto, AuditLogFilters } from '../features/admin/types/logs'
import { humanizeLabel } from '../format/text'

// Filters live in the URL, so a view of the log can be bookmarked.
const PARAM = {
  from: 'from',
  to: 'to',
  user: 'user',
  action: 'action',
  result: 'result',
  target: 'target',
  offset: 'offset',
} as const

const RESULTS = [
  { id: 'ok', name: 'Succeeded' },
  { id: 'failed', name: 'Failed' },
] as const

// "read_ai_log" -> "Read AI log".
function actionLabel(action: string): string {
  return humanizeLabel(action).replace(/\bai\b/g, 'AI')
}

function who(entry: AuditEntryDto): string {
  if (entry.user_name) return entry.user_name
  if (entry.role === 'telephony') return 'Telephony provider'
  if (entry.user_id) return 'A user since removed'
  const triedAs = entry.detail?.email
  return typeof triedAs === 'string' ? `Not signed in (tried as ${triedAs})` : 'Not signed in'
}

function Target({ entry }: { entry: AuditEntryDto }) {
  if (!entry.target_id) return <>—</>
  const label = humanizeLabel(entry.target_type ?? 'item')
  if (entry.target_type === 'call') {
    return (
      <>
        {label}{' '}
        <Link
          className="text-link"
          to={`/post-call-analysis?call_id=${encodeURIComponent(entry.target_id)}`}
        >
          {entry.target_id}
        </Link>
      </>
    )
  }
  return (
    <>
      {label} <span className="log-table__id">{entry.target_id}</span>
    </>
  )
}

export function AuditLogPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [loaded, setLoaded] = useState<{
    key: string
    log: AuditLogDto | null
    error: string | null
  } | null>(null)

  const value = (name: string) => searchParams.get(name) ?? ''
  const offset = Math.max(0, Number(value(PARAM.offset)) || 0)
  const filters: AuditLogFilters = {
    userId: value(PARAM.user) || undefined,
    action: value(PARAM.action) || undefined,
    succeeded: value(PARAM.result) === 'ok' ? true : value(PARAM.result) === 'failed' ? false : undefined,
    targetId: value(PARAM.target) || undefined,
    occurredFrom: localMidnight(value(PARAM.from)),
    occurredTo: localMidnight(value(PARAM.to), 1),
  }
  const requestKey = JSON.stringify([filters, offset])

  useEffect(() => {
    let cancelled = false
    const [requested, from] = JSON.parse(requestKey) as [AuditLogFilters, number]
    logRestService
      .getAuditLog(requested, LOG_PAGE_SIZE, from)
      .then((log) => {
        if (!cancelled) setLoaded({ key: requestKey, log, error: null })
      })
      .catch((err) => {
        if (cancelled) return
        setLoaded({
          key: requestKey,
          log: null,
          error: err instanceof ApiError ? err.message : 'Unable to load the audit log.',
        })
      })
    return () => {
      cancelled = true
    }
  }, [requestKey])

  const setFilter = (name: string, next: string) =>
    setSearchParams(withFilter(searchParams, { [name]: next || null }), { replace: true })
  const filtered = Object.values(PARAM).some(
    (name) => name !== PARAM.offset && searchParams.has(name),
  )

  // The last answer stays on screen while the next one loads.
  const log = loaded?.log ?? null
  const isLoading = loaded?.key !== requestKey
  const error = !isLoading ? (loaded?.error ?? null) : null

  const choice = (
    name: string,
    label: string,
    options: ReadonlyArray<{ id: string; name: string }>,
    all: string,
  ) => (
    <label className="call-filters__choice">
      <span>{label}</span>
      <select value={value(name)} onChange={(event) => setFilter(name, event.target.value)}>
        <option value="">{all}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.name}
          </option>
        ))}
      </select>
    </label>
  )

  return (
    <section className="page-shell">
      <p className="customer-panel__muted">
        <Link className="text-link" to="/administration">
          ← Administration
        </Link>
      </p>

      <div className="panel call-filters" role="search" aria-label="Audit log filters">
        <div className="call-filters__row">
          <fieldset className="call-filters__range">
            <legend>Date</legend>
            <label className="call-filters__date">
              <span>From</span>
              <input
                type="date"
                value={value(PARAM.from)}
                max={value(PARAM.to) || undefined}
                onChange={(event) => setFilter(PARAM.from, event.target.value)}
              />
            </label>
            <label className="call-filters__date">
              <span>To</span>
              <input
                type="date"
                value={value(PARAM.to)}
                min={value(PARAM.from) || undefined}
                onChange={(event) => setFilter(PARAM.to, event.target.value)}
              />
            </label>
          </fieldset>
          {choice(
            PARAM.user,
            'User',
            (log?.users ?? []).map((user) => ({ id: user.user_id, name: user.name })),
            'Everyone',
          )}
          {choice(
            PARAM.action,
            'Action',
            (log?.actions ?? []).map((action) => ({ id: action, name: actionLabel(action) })),
            'Every action',
          )}
          {choice(PARAM.result, 'Result', RESULTS, 'Any result')}
          <div className="call-filters__actions">
            {isLoading && log && <span className="call-filters__status">Loading…</span>}
            <button
              type="button"
              className="button button--secondary"
              onClick={() => setSearchParams(new URLSearchParams(), { replace: true })}
              disabled={!filtered}
            >
              Clear filters
            </button>
          </div>
        </div>
        {value(PARAM.target) && (
          <p className="customer-panel__muted">
            Only entries about <strong>{value(PARAM.target)}</strong>.
          </p>
        )}
      </div>

      {error && (
        <StatePanel variant="error" title="Could not load the audit log" description={error} compact />
      )}
      {!log && !error && <StatePanel variant="loading" title="Loading the audit log…" compact />}

      {log && !error && (
        <section className="panel">
          <div className="section-heading">
            <div>
              <h3 className="section-title">Who did what</h3>
              <p className="customer-panel__muted">
                Every change made through the application, sign-ins, recordings listened to,
                downloads, and each time this log or the AI log was opened. Kept for{' '}
                {Math.round(log.retention_days)} days. What was typed or said is never stored
                here.
              </p>
            </div>
          </div>

          {log.entries.length === 0 ? (
            <StatePanel
              title={filtered ? 'Nothing matches these filters' : 'Nothing has been recorded yet'}
              compact
            />
          ) : (
            <>
              <div className="log-table-scroll">
                <table className="log-table">
                  <thead>
                    <tr>
                      <th scope="col">When</th>
                      <th scope="col">Who</th>
                      <th scope="col">Action</th>
                      <th scope="col">Done to</th>
                      <th scope="col">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {log.entries.map((entry) => (
                      <tr key={entry.entry_id ?? `${entry.occurred_at}:${entry.request_id}`}>
                        <td>
                          <RecordTime seconds={entry.occurred_at} />
                        </td>
                        <td>
                          {who(entry)}
                          {entry.role && entry.role !== 'telephony' && (
                            <span className="log-table__sub">{humanizeLabel(entry.role)}</span>
                          )}
                        </td>
                        <td>
                          {actionLabel(entry.action)}
                          <span className="log-table__sub">
                            {entry.method} {entry.path}
                          </span>
                        </td>
                        <td>
                          <Target entry={entry} />
                        </td>
                        <td>
                          <span
                            className={`badge ${entry.succeeded ? 'badge--success' : 'badge--danger'}`}
                          >
                            {entry.succeeded ? 'Succeeded' : 'Failed'}
                          </span>
                          <span className="log-table__sub">
                            Status {entry.status_code}
                            {entry.ip_address ? ` · from ${entry.ip_address}` : ''}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <LogPager
                offset={offset}
                shown={log.entries.length}
                total={log.total}
                noun={filtered ? 'matching entries' : 'entries'}
                onOffset={(next) =>
                  setSearchParams(
                    withFilter(searchParams, { [PARAM.offset]: next ? String(next) : null }),
                  )
                }
              />
            </>
          )}
        </section>
      )}
    </section>
  )
}
