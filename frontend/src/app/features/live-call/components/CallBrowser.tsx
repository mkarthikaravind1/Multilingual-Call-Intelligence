import { useEffect, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import { toCallMetadataViewModel } from '../adapters/toViewModel'
import { useCallDirectory } from '../hooks/useCallDirectory'
import { callRestService, type CallListFilters } from '../services/callRestService'
import type { CallDirectoryEntryDto } from '../types/dto'
import type { CallMetadataViewModel } from '../types/view-models'
import { CallTable } from './CallTable'

const PAGE_SIZE = 20
const SEARCH_DELAY_MS = 300

// Filters live in the URL so they survive opening a call and coming back.
const PARAM = {
  customer: 'customer',
  phone: 'phone',
  status: 'status',
  high: 'high_escalation',
  startedFrom: 'called_from',
  startedTo: 'called_to',
  resolvedFrom: 'resolved_from',
  resolvedTo: 'resolved_to',
  location: 'location',
  executive: 'executive',
  direction: 'direction',
  offset: 'offset',
} as const

const DIRECTION_OPTIONS = [
  { id: 'inbound', name: 'Incoming' },
  { id: 'outbound', name: 'Outgoing' },
] as const

type DateParam =
  | typeof PARAM.startedFrom
  | typeof PARAM.startedTo
  | typeof PARAM.resolvedFrom
  | typeof PARAM.resolvedTo

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'completed', label: 'Completed' },
] as const

type CallStatusOption = (typeof STATUS_OPTIONS)[number]['value']

const FILTER_PARAMS = Object.values(PARAM).filter((name) => name !== PARAM.offset)

// <input type="date"> values are local calendar days ("2026-10-02"); the API
// takes epoch seconds, from inclusive and to exclusive.
function localMidnight(day: string, addDays = 0): number | undefined {
  const [year, month, date] = day.split('-').map(Number)
  if (!year || !month || !date) return undefined
  return new Date(year, month - 1, date + addDays).getTime() / 1000
}

function toApiFilters(params: URLSearchParams): CallListFilters {
  const day = (name: DateParam, addDays = 0) => localMidnight(params.get(name) ?? '', addDays)
  return {
    statuses: params
      .getAll(PARAM.status)
      .filter((s): s is CallStatusOption => STATUS_OPTIONS.some((o) => o.value === s)),
    highEscalation: params.get(PARAM.high) === 'true',
    customer: params.get(PARAM.customer) ?? undefined,
    phone: params.get(PARAM.phone) ?? undefined,
    startedFrom: day(PARAM.startedFrom),
    startedTo: day(PARAM.startedTo, 1),
    resolvedFrom: day(PARAM.resolvedFrom),
    resolvedTo: day(PARAM.resolvedTo, 1),
    locationId: params.get(PARAM.location) ?? undefined,
    executiveUserId: params.get(PARAM.executive) ?? undefined,
    direction: DIRECTION_OPTIONS.find((o) => o.id === params.get(PARAM.direction))?.id,
  }
}

// Starts from the address bar rather than a render's searchParams, which can
// be stale when several filters change in quick succession (or from a timer).
function withChanges(changes: Record<string, string | string[] | null>): URLSearchParams {
  const next = new URLSearchParams(window.location.search)
  for (const [name, value] of Object.entries(changes)) {
    next.delete(name)
    for (const item of [value ?? []].flat()) {
      if (item) next.append(name, item)
    }
  }
  if (!(PARAM.offset in changes)) next.delete(PARAM.offset)
  return next
}

type ListState = {
  requestKey: string
  calls: CallMetadataViewModel[]
  total: number
  error: string | null
}

type CallBrowserProps = {
  // Shown when there are no calls at all (no filters set).
  emptyState: ReactNode
}

export function CallBrowser({ emptyState }: CallBrowserProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [reloadCount, setReloadCount] = useState(0)
  const directory = useCallDirectory()
  const [result, setResult] = useState<ListState | null>(null)

  // Typed text is applied after a short pause, not on every keystroke.
  const [customerDraft, setCustomerDraft] = useState(searchParams.get(PARAM.customer) ?? '')
  const [phoneDraft, setPhoneDraft] = useState(searchParams.get(PARAM.phone) ?? '')

  const offset = Math.max(0, Number(searchParams.get(PARAM.offset)) || 0)
  const filterParams = new URLSearchParams()
  for (const name of FILTER_PARAMS) {
    for (const value of searchParams.getAll(name)) filterParams.append(name, value)
  }
  const filterKey = filterParams.toString()
  const hasFilters = filterKey !== ''
  const requestKey = `${filterKey}|${offset}|${reloadCount}`
  const isLoading = result?.requestKey !== requestKey

  // Changes filters (null removes one) and goes back to the first page.
  const updateParams = (changes: Record<string, string | string[] | null>) =>
    setSearchParams(withChanges(changes), { replace: true })

  const appliedCustomer = searchParams.get(PARAM.customer) ?? ''
  const appliedPhone = searchParams.get(PARAM.phone) ?? ''

  useEffect(() => {
    if (customerDraft.trim() === appliedCustomer && phoneDraft.trim() === appliedPhone) {
      return
    }
    const timer = window.setTimeout(() => {
      setSearchParams(
        withChanges({
          [PARAM.customer]: customerDraft.trim() || null,
          [PARAM.phone]: phoneDraft.trim() || null,
        }),
        { replace: true },
      )
    }, SEARCH_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [customerDraft, phoneDraft, appliedCustomer, appliedPhone, setSearchParams])

  useEffect(() => {
    let cancelled = false

    callRestService
      .listCalls(PAGE_SIZE, offset, toApiFilters(new URLSearchParams(filterKey)))
      .then((response) => {
        if (cancelled) return
        setResult({
          requestKey,
          calls: response.items.map(toCallMetadataViewModel),
          total: response.total,
          error: null,
        })
      })
      .catch((err) => {
        if (cancelled) return
        setResult({
          requestKey,
          calls: [],
          total: 0,
          error: err instanceof ApiError ? err.message : 'Unable to load calls.',
        })
      })

    return () => {
      cancelled = true
    }
  }, [filterKey, offset, requestKey])

  const statuses = searchParams.getAll(PARAM.status)
  const toggleStatus = (status: CallStatusOption, checked: boolean) => {
    const others = new URLSearchParams(window.location.search)
      .getAll(PARAM.status)
      .filter((s) => s !== status)
    updateParams({ [PARAM.status]: checked ? [...others, status] : others })
  }

  const clearFilters = () => {
    setCustomerDraft('')
    setPhoneDraft('')
    updateParams(Object.fromEntries(FILTER_PARAMS.map((name) => [name, null])))
  }

  const dateInput = (name: DateParam, label: string, bound: { min?: string; max?: string }) => (
    <label className="call-filters__date">
      <span>{label}</span>
      <input
        type="date"
        value={searchParams.get(name) ?? ''}
        min={bound.min}
        max={bound.max}
        onChange={(event) => updateParams({ [name]: event.target.value || null })}
      />
    </label>
  )

  // A deactivated entry is offered only while it is the one chosen.
  const choice = (
    name: typeof PARAM.location | typeof PARAM.executive | typeof PARAM.direction,
    label: string,
    options: ReadonlyArray<Pick<CallDirectoryEntryDto, 'id' | 'name'> & { is_active?: boolean }>,
  ) => {
    const value = searchParams.get(name) ?? ''
    return (
      <label className="call-filters__choice">
        <span>{label}</span>
        <select
          value={value}
          onChange={(event) => updateParams({ [name]: event.target.value || null })}
        >
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
  }

  const dateRange = (title: string, from: DateParam, to: DateParam) => {
    const fromValue = searchParams.get(from) ?? undefined
    const toValue = searchParams.get(to) ?? undefined
    return (
      <fieldset className="call-filters__range">
        <legend>{title}</legend>
        {dateInput(from, 'From', { max: toValue })}
        {dateInput(to, 'To', { min: fromValue })}
        {fromValue && toValue && fromValue > toValue && (
          <span className="call-filters__hint" role="alert">
            “From” is after “To”.
          </span>
        )}
      </fieldset>
    )
  }

  const current = result
  const refreshButton = (
    <button
      type="button"
      className="button button--secondary"
      onClick={() => setReloadCount((count) => count + 1)}
      disabled={isLoading}
    >
      Refresh
    </button>
  )

  let body: ReactNode
  if (!current) {
    body = <StatePanel variant="loading" title="Loading calls…" compact />
  } else if (current.error) {
    body = (
      <StatePanel
        variant="error"
        title="Could not load calls"
        description={current.error}
        action={refreshButton}
      />
    )
  } else if (current.total === 0) {
    body = hasFilters ? (
      <StatePanel
        title="No calls match these filters"
        description="Try a different search or a wider date range."
        action={
          <button type="button" className="button button--secondary" onClick={clearFilters}>
            Clear filters
          </button>
        }
        compact
      />
    ) : (
      emptyState
    )
  } else {
    const firstShown = offset + 1
    const lastShown = offset + current.calls.length
    const page = Math.floor(offset / PAGE_SIZE) + 1
    const pageCount = Math.max(1, Math.ceil(current.total / PAGE_SIZE))
    body = (
      <>
        <CallTable calls={current.calls} />
        <div className="pager">
          <span>
            Showing <strong>{firstShown}–{lastShown}</strong> of{' '}
            <strong>{current.total}</strong> calls · Page {page} of {pageCount}
          </span>
          <div className="button-row">
            {refreshButton}
            <button
              type="button"
              className="button button--secondary"
              onClick={() =>
                updateParams({ [PARAM.offset]: String(Math.max(0, offset - PAGE_SIZE)) })
              }
              disabled={offset === 0 || isLoading}
            >
              Previous
            </button>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => updateParams({ [PARAM.offset]: String(offset + PAGE_SIZE) })}
              disabled={lastShown >= current.total || isLoading}
            >
              Next
            </button>
          </div>
        </div>
      </>
    )
  }

  return (
    <div className="call-browser">
      <div className="panel call-filters" role="search" aria-label="Filter calls">
        <div className="call-filters__row">
          <label className="call-filters__search">
            <span>Customer</span>
            <input
              type="search"
              placeholder="Customer name or vehicle number"
              value={customerDraft}
              maxLength={100}
              onChange={(event) => setCustomerDraft(event.target.value)}
            />
          </label>
          <label className="call-filters__search">
            <span>Phone number</span>
            <input
              type="search"
              inputMode="tel"
              placeholder="e.g. 98450 00001"
              value={phoneDraft}
              maxLength={32}
              onChange={(event) => setPhoneDraft(event.target.value)}
            />
          </label>
          <fieldset className="call-filters__checks">
            <legend>Show</legend>
            {STATUS_OPTIONS.map((option) => (
              <label key={option.value} className="call-filters__check">
                <input
                  type="checkbox"
                  checked={statuses.includes(option.value)}
                  onChange={(event) => toggleStatus(option.value, event.target.checked)}
                />
                {option.label}
              </label>
            ))}
            <label className="call-filters__check">
              <input
                type="checkbox"
                checked={searchParams.get(PARAM.high) === 'true'}
                onChange={(event) =>
                  updateParams({ [PARAM.high]: event.target.checked ? 'true' : null })
                }
              />
              High escalation
            </label>
          </fieldset>
        </div>

        <div className="call-filters__row">
          {choice(PARAM.location, 'Location', directory.locations)}
          {choice(PARAM.executive, 'Executive', directory.executives)}
          {choice(PARAM.direction, 'Direction', DIRECTION_OPTIONS)}
          {dateRange('Call date', PARAM.startedFrom, PARAM.startedTo)}
          {dateRange('Resolved date', PARAM.resolvedFrom, PARAM.resolvedTo)}
          <div className="call-filters__actions">
            {isLoading && current && (
              <span className="call-filters__status" role="status">
                <span className="spinner" aria-hidden="true" /> Updating…
              </span>
            )}
            <button
              type="button"
              className="button button--secondary"
              onClick={clearFilters}
              disabled={!hasFilters && !customerDraft && !phoneDraft}
            >
              Clear filters
            </button>
          </div>
        </div>
      </div>

      {body}
    </div>
  )
}
