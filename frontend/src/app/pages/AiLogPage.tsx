import { Fragment, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { RecordTime } from '../components/RecordTime'
import { StatePanel } from '../components/StatePanel'
import { LogPager } from '../features/admin/components/LogPager'
import { LOG_PAGE_SIZE, localMidnight, withFilter } from '../features/admin/logFilters'
import { logRestService } from '../features/admin/services/logRestService'
import type {
  AiLogDto,
  AiLogEntryDetailDto,
  AiLogEntryDto,
  AiLogFilters,
  AiOutcome,
} from '../features/admin/types/logs'
import { humanizeLabel } from '../format/text'

// Filters live in the URL: a finished call links here with its call id.
const PARAM = {
  call: 'call_id',
  task: 'task',
  outcome: 'outcome',
  from: 'from',
  to: 'to',
  offset: 'offset',
} as const

const OUTCOMES: Array<{ id: AiOutcome; name: string; badge: string }> = [
  { id: 'answered', name: 'Answered', badge: 'badge--success' },
  { id: 'unusable', name: 'Unusable answer', badge: 'badge--warning' },
  { id: 'failed', name: 'Failed', badge: 'badge--danger' },
]
const SEARCH_DELAY_MS = 300

const count = (value: number) => value.toLocaleString()

function seconds(milliseconds: number): string {
  return `${(milliseconds / 1000).toFixed(milliseconds < 10000 ? 2 : 1)} s`
}

function tokens(entry: AiLogEntryDto): string {
  if (entry.prompt_tokens === null && entry.completion_tokens === null) return '—'
  return `${count(entry.prompt_tokens ?? 0)} in · ${count(entry.completion_tokens ?? 0)} out`
}

type OpenEntry =
  | { entryId: string; detail: AiLogEntryDetailDto; error: null }
  | { entryId: string; detail: null; error: string | null }

function EntryText({ open }: { open: OpenEntry }) {
  if (open.error) return <p className="inline-notice">{open.error}</p>
  if (!open.detail) return <p className="customer-panel__muted">Loading…</p>
  const { prompt, answer, note } = open.detail
  if (prompt === null && answer === null) {
    return (
      <p className="customer-panel__muted">
        {note ? `${note} ` : ''}The text of this request was not kept.
      </p>
    )
  }
  return (
    <div className="log-entry-text">
      {note && <p className="inline-notice">{note}</p>}
      <div>
        <p className="panel__label">Asked</p>
        <pre>{prompt ?? '(not kept)'}</pre>
      </div>
      <div>
        <p className="panel__label">Answered</p>
        <pre>{answer ?? '(no answer)'}</pre>
      </div>
    </div>
  )
}

export function AiLogPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [loaded, setLoaded] = useState<{
    key: string
    log: AiLogDto | null
    error: string | null
  } | null>(null)
  const [open, setOpen] = useState<OpenEntry | null>(null)

  const value = (name: string) => searchParams.get(name) ?? ''
  const appliedCall = value(PARAM.call)
  const [callDraft, setCallDraft] = useState(appliedCall)
  const offset = Math.max(0, Number(value(PARAM.offset)) || 0)
  const filters: AiLogFilters = {
    callId: appliedCall || undefined,
    task: value(PARAM.task) || undefined,
    outcome: OUTCOMES.find((o) => o.id === value(PARAM.outcome))?.id,
    startedFrom: localMidnight(value(PARAM.from)),
    startedTo: localMidnight(value(PARAM.to), 1),
  }
  const requestKey = JSON.stringify([filters, offset])

  // The call id is applied a moment after typing stops.
  useEffect(() => {
    if (callDraft.trim() === appliedCall) return
    const timer = window.setTimeout(() => {
      setSearchParams(
        withFilter(new URLSearchParams(window.location.search), {
          [PARAM.call]: callDraft.trim() || null,
        }),
        { replace: true },
      )
    }, SEARCH_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [callDraft, appliedCall, setSearchParams])

  useEffect(() => {
    let cancelled = false
    const [requested, from] = JSON.parse(requestKey) as [AiLogFilters, number]
    logRestService
      .getAiLog(requested, LOG_PAGE_SIZE, from)
      .then((log) => {
        if (!cancelled) setLoaded({ key: requestKey, log, error: null })
      })
      .catch((err) => {
        if (cancelled) return
        setLoaded({
          key: requestKey,
          log: null,
          error: err instanceof ApiError ? err.message : 'Unable to load the AI log.',
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

  const toggle = (entryId: string) => {
    if (open?.entryId === entryId) {
      setOpen(null)
      return
    }
    setOpen({ entryId, detail: null, error: null })
    logRestService
      .getAiLogEntry(entryId)
      .then((detail) =>
        setOpen((current) =>
          current?.entryId === entryId ? { entryId, detail, error: null } : current,
        ),
      )
      .catch((err) =>
        setOpen((current) =>
          current?.entryId === entryId
            ? {
                entryId,
                detail: null,
                error: err instanceof ApiError ? err.message : 'Unable to load this request.',
              }
            : current,
        ),
      )
  }

  // The last answer stays on screen while the next one loads.
  const log = loaded?.log ?? null
  const isLoading = loaded?.key !== requestKey
  const error = !isLoading ? (loaded?.error ?? null) : null
  const keepsText = log?.mode === 'full'

  return (
    <section className="page-shell">
      <p className="customer-panel__muted">
        <Link className="text-link" to="/administration">
          ← Administration
        </Link>
      </p>

      <div className="panel call-filters" role="search" aria-label="AI log filters">
        <div className="call-filters__row">
          <label className="call-filters__search">
            <span>Call id</span>
            <input
              type="search"
              value={callDraft}
              placeholder="All calls"
              onChange={(event) => setCallDraft(event.target.value)}
            />
          </label>
          <label className="call-filters__choice">
            <span>Task</span>
            <select
              value={value(PARAM.task)}
              onChange={(event) => setFilter(PARAM.task, event.target.value)}
            >
              <option value="">Every task</option>
              {(log?.tasks ?? []).map((task) => (
                <option key={task} value={task}>
                  {humanizeLabel(task)}
                </option>
              ))}
            </select>
          </label>
          <label className="call-filters__choice">
            <span>Outcome</span>
            <select
              value={value(PARAM.outcome)}
              onChange={(event) => setFilter(PARAM.outcome, event.target.value)}
            >
              <option value="">Any outcome</option>
              {OUTCOMES.map((outcome) => (
                <option key={outcome.id} value={outcome.id}>
                  {outcome.name}
                </option>
              ))}
            </select>
          </label>
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
          <div className="call-filters__actions">
            {isLoading && log && <span className="call-filters__status">Loading…</span>}
            <button
              type="button"
              className="button button--secondary"
              onClick={() => {
                setCallDraft('')
                setSearchParams(new URLSearchParams(), { replace: true })
              }}
              disabled={!filtered}
            >
              Clear filters
            </button>
          </div>
        </div>
      </div>

      {error && (
        <StatePanel variant="error" title="Could not load the AI log" description={error} compact />
      )}
      {!log && !error && <StatePanel variant="loading" title="Loading the AI log…" compact />}

      {log && !error && (
        <section className="panel">
          <div className="section-heading">
            <div>
              <h3 className="section-title">What the AI was asked and answered</h3>
              <p className="customer-panel__muted">
                {log.mode === 'off'
                  ? 'The AI log is switched off (AI_LOG_MODE=off): new requests are not recorded.'
                  : keepsText
                    ? `Every request to the AI, with its full text, kept for ${Math.round(log.retention_days)} days. The text contains what customers said: opening a request is recorded in the audit log.`
                    : `Every request to the AI, kept for ${Math.round(log.retention_days)} days. Only the details are kept (AI_LOG_MODE=details), not what was asked or answered.`}
              </p>
            </div>
          </div>

          {log.total > 0 && (
            <div className="list-card__facts">
              <span>
                Requests: <strong>{count(log.totals.requests)}</strong>
              </span>
              <span>
                Tokens sent: <strong>{count(log.totals.prompt_tokens)}</strong>
              </span>
              <span>
                Tokens received: <strong>{count(log.totals.completion_tokens)}</strong>
              </span>
              <span>
                Total tokens: <strong>{count(log.totals.total_tokens)}</strong>
              </span>
              {log.totals.uncounted > 0 && (
                <span>
                  ({count(log.totals.uncounted)} without a token count)
                </span>
              )}
            </div>
          )}

          {log.entries.length === 0 ? (
            <StatePanel
              title={filtered ? 'Nothing matches these filters' : 'No requests have been recorded yet'}
              compact
            />
          ) : (
            <>
              <div className="log-table-scroll">
                <table className="log-table">
                  <thead>
                    <tr>
                      <th scope="col">When</th>
                      <th scope="col">Call</th>
                      <th scope="col">Task</th>
                      <th scope="col">Outcome</th>
                      <th scope="col">Time taken</th>
                      <th scope="col">Tokens</th>
                      <th scope="col">
                        <span className="visually-hidden">Text</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {log.entries.map((entry) => {
                      const outcome = OUTCOMES.find((o) => o.id === entry.outcome)
                      const isOpen = open?.entryId === entry.entry_id
                      return (
                        <Fragment key={entry.entry_id}>
                          <tr>
                            <td>
                              <RecordTime seconds={entry.started_at} />
                            </td>
                            <td>
                              {entry.call_id ? (
                                <Link
                                  className="text-link"
                                  to={`/post-call-analysis?call_id=${encodeURIComponent(entry.call_id)}`}
                                >
                                  {entry.call_id}
                                </Link>
                              ) : (
                                'No single call'
                              )}
                            </td>
                            <td>
                              {humanizeLabel(entry.task)}
                              <span className="log-table__sub">
                                {entry.model}
                                {entry.attempt > 1 ? ' · asked again' : ''}
                              </span>
                            </td>
                            <td>
                              <span className={`badge ${outcome?.badge ?? ''}`}>
                                {outcome?.name ?? humanizeLabel(entry.outcome)}
                              </span>
                              {entry.note && !isOpen && (
                                <span className="log-table__sub log-table__note">{entry.note}</span>
                              )}
                            </td>
                            <td>{seconds(entry.duration_ms)}</td>
                            <td>{tokens(entry)}</td>
                            <td>
                              <button
                                type="button"
                                className="button button--secondary"
                                aria-expanded={isOpen}
                                onClick={() => toggle(entry.entry_id)}
                              >
                                {isOpen ? 'Hide' : keepsText ? 'Show text' : 'Details'}
                              </button>
                            </td>
                          </tr>
                          {isOpen && open && (
                            <tr className="log-table__detail">
                              <td colSpan={7}>
                                <EntryText open={open} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <LogPager
                offset={offset}
                shown={log.entries.length}
                total={log.total}
                noun={filtered ? 'matching requests' : 'requests'}
                onOffset={(next) => {
                  setOpen(null)
                  setSearchParams(
                    withFilter(searchParams, { [PARAM.offset]: next ? String(next) : null }),
                  )
                }}
              />
            </>
          )}
        </section>
      )}
    </section>
  )
}
