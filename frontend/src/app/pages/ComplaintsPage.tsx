import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { RecordTime } from '../components/RecordTime'
import { StatePanel } from '../components/StatePanel'
import { ComplaintLifecycleCard } from '../features/complaints/components/ComplaintLifecycleCard'
import { customerLabel } from '../features/complaints/customerLabel'
import { complaintRestService } from '../features/complaints/services/complaintRestService'
import { COMPLAINT_CATEGORIES } from '../features/complaints/types/dto'

import type {
  ComplaintDto,
  ComplaintQueueState,
  ComplaintStage,
} from '../features/complaints/types/dto'

// Complaints from calls in progress appear without a manual refresh.
const REFRESH_INTERVAL_MS = 15000

const VIEWS: { value: ComplaintQueueState; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All' },
]

// The stages of the card's track, filtered by the complaint's current stage.
const STAGES: { value: ComplaintStage; label: string }[] = [
  { value: 'detected', label: 'Detected' },
  { value: 'probed', label: 'Probed' },
  { value: 'covered', label: 'Covered' },
  { value: 'outcome', label: 'Outcome' },
  { value: 'follow_up', label: 'Follow-up' },
]

type GroupBy = 'none' | 'call' | 'customer'

const GROUPINGS: { value: GroupBy; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'call', label: 'Call' },
  { value: 'customer', label: 'Customer' },
]

// Remembered per browser; storage may be unavailable (private windows).
const GROUP_BY_KEY = 'complaints.groupBy'

function storedGroupBy(): GroupBy {
  try {
    const value = window.localStorage.getItem(GROUP_BY_KEY)
    return value === 'call' || value === 'customer' ? value : 'none'
  } catch {
    return 'none'
  }
}

function storeGroupBy(value: GroupBy) {
  try {
    window.localStorage.setItem(GROUP_BY_KEY, value)
  } catch {
    // Not remembered; the choice still applies now.
  }
}

type ComplaintGroup = {
  key: string
  complaints: ComplaintDto[]
  // Grouped by customer, with the customer identified.
  isCustomer: boolean
}

// Groups in the order their first complaint is listed, so the queue's order
// (follow-ups first, then the oldest) carries over to the groups. A complaint
// whose customer is not identified is grouped by its call.
function groupComplaints(complaints: ComplaintDto[], groupBy: Exclude<GroupBy, 'none'>) {
  const groups = new Map<string, ComplaintGroup>()
  for (const complaint of complaints) {
    const byCustomer = groupBy === 'customer' && complaint.customer_id !== null
    const key = byCustomer ? `customer:${complaint.customer_id}` : `call:${complaint.call_id}`
    const group = groups.get(key)
    if (group) {
      group.complaints.push(complaint)
    } else {
      groups.set(key, { key, complaints: [complaint], isCustomer: byCustomer })
    }
  }
  return [...groups.values()]
}

function GroupHeading({ group }: { group: ComplaintGroup }) {
  const first = group.complaints[0]
  const customer = customerLabel(first)
  const open = group.complaints.filter((c) => c.is_open).length
  const calls = new Set(group.complaints.map((c) => c.call_id)).size
  const count = group.complaints.length
  const counts = [
    group.isCustomer ? `${calls} ${calls === 1 ? 'call' : 'calls'}` : null,
    `${count} ${count === 1 ? 'complaint' : 'complaints'}`,
    `${open} open`,
  ]
    .filter(Boolean)
    .join(' · ')

  if (group.isCustomer) {
    return (
      <header className="complaint-group__heading">
        <h2 className="complaint-group__title">
          {customer ?? `Customer ${first.customer_id}`}
        </h2>
        <span className="complaint-group__facts">{counts}</span>
      </header>
    )
  }
  return (
    <header className="complaint-group__heading">
      <h2 className="complaint-group__title">
        <Link
          className="text-link"
          to={`/post-call-analysis?call_id=${encodeURIComponent(first.call_id)}`}
          title="Open the post-call analysis"
        >
          {first.call_id}
        </Link>
      </h2>
      <span className="complaint-group__facts">
        {first.call_started_at != null && <RecordTime seconds={first.call_started_at} />}
        <span>ICR: {first.icr_name ?? 'Not recorded'}</span>
        <span>{customer ? `Customer: ${customer}` : 'Customer not identified'}</span>
        <span>{counts}</span>
      </span>
    </header>
  )
}

const EMPTY_MESSAGES: Record<ComplaintQueueState, { title: string; description: string }> = {
  open: {
    title: 'No open complaints',
    description:
      'Complaints appear here as soon as they are detected on a call. Those a call ended without resolving are listed first.',
  },
  resolved: {
    title: 'No resolved complaints yet',
    description: 'Complaints resolved on a call or afterwards are kept here with their history.',
  },
  all: {
    title: 'No complaints yet',
    description: 'Every complaint detected on a call is tracked here from detection to closure.',
  },
}

function toggled<T>(values: T[], value: T, checked: boolean): T[] {
  return checked ? [...values.filter((v) => v !== value), value] : values.filter((v) => v !== value)
}

export function ComplaintsPage() {
  const [view, setView] = useState<ComplaintQueueState>('open')
  const [categories, setCategories] = useState<string[]>([])
  const [stages, setStages] = useState<ComplaintStage[]>([])
  const [groupBy, setGroupBy] = useState<GroupBy>(storedGroupBy)
  const [complaints, setComplaints] = useState<ComplaintDto[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadCount, setReloadCount] = useState(0)
  // Built-ins plus accepted emerging themes; the built-ins until loaded.
  const [categoryOptions, setCategoryOptions] = useState<string[]>([...COMPLAINT_CATEGORIES])

  useEffect(() => {
    let cancelled = false
    complaintRestService
      .listCategories()
      .then((list) => {
        if (!cancelled) {
          setCategoryOptions(list.map((category) => category.name))
        }
      })
      .catch(() => {
        // Keep the built-in categories; the queue still loads.
      })
    return () => {
      cancelled = true
    }
  }, [])

  // JSON, not a joined string: category names may contain commas.
  const filterKey = JSON.stringify({ view, categories, stages })
  const hasFilters = categories.length > 0 || stages.length > 0

  const load = useCallback(
    async (state: ComplaintQueueState, filters: { categories: string[]; stages: ComplaintStage[] }) => {
      try {
        setComplaints(await complaintRestService.listQueue(state, filters))
        setError(null)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Unable to load complaints.')
      } finally {
        setIsLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    let cancelled = false
    const { view: state, ...filters } = JSON.parse(filterKey) as {
      view: ComplaintQueueState
      categories: string[]
      stages: ComplaintStage[]
    }
    const refresh = () => {
      if (!cancelled) {
        void load(state, filters)
      }
    }
    refresh()
    const intervalId = window.setInterval(refresh, REFRESH_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [filterKey, load, reloadCount])

  // Every filter change shows a fresh list rather than the previous one.
  const changeFilters = (apply: () => void) => {
    setIsLoading(true)
    setComplaints([])
    apply()
  }

  // A saved change may move the complaint out of the current filters, so the
  // list is fetched again; until then the card shows the saved state.
  const handleUpdated = (updated: ComplaintDto) => {
    setComplaints((current) =>
      current.map((item) => (item.complaint_id === updated.complaint_id ? updated : item)),
    )
    setReloadCount((count) => count + 1)
  }

  const followUps = complaints.filter((c) => c.is_open && c.follow_up_required).length

  return (
    <section className="page-shell">
      <div className="panel call-filters" role="search" aria-label="Filter complaints">
        <div className="call-filters__row">
          <fieldset className="call-filters__checks">
            <legend>Show</legend>
            {VIEWS.map((item) => (
              <label key={item.value} className="call-filters__check">
                <input
                  type="radio"
                  name="complaint-view"
                  value={item.value}
                  checked={view === item.value}
                  onChange={() => changeFilters(() => setView(item.value))}
                />
                {item.label}
              </label>
            ))}
          </fieldset>

          <fieldset className="call-filters__checks">
            <legend>Stage</legend>
            {STAGES.map((stage) => (
              <label key={stage.value} className="call-filters__check">
                <input
                  type="checkbox"
                  checked={stages.includes(stage.value)}
                  onChange={(event) =>
                    changeFilters(() =>
                      setStages((current) => toggled(current, stage.value, event.target.checked)),
                    )
                  }
                />
                {stage.label}
              </label>
            ))}
          </fieldset>

          <fieldset className="call-filters__checks">
            <legend>Group by</legend>
            {GROUPINGS.map((item) => (
              <label key={item.value} className="call-filters__check">
                <input
                  type="radio"
                  name="complaint-group-by"
                  value={item.value}
                  checked={groupBy === item.value}
                  onChange={() => {
                    setGroupBy(item.value)
                    storeGroupBy(item.value)
                  }}
                />
                {item.label}
              </label>
            ))}
          </fieldset>

          <div className="call-filters__actions">
            {view === 'open' && !isLoading && !error && (
              <span className="customer-panel__muted">
                {complaints.length} open · {followUps} flagged for follow-up
              </span>
            )}
            <button
              type="button"
              className="button button--secondary"
              disabled={!hasFilters}
              onClick={() =>
                changeFilters(() => {
                  setCategories([])
                  setStages([])
                })
              }
            >
              Clear filters
            </button>
          </div>
        </div>

        <fieldset className="call-filters__checks">
          <legend>Category</legend>
          {categoryOptions.map((category) => (
            <label key={category} className="call-filters__check">
              <input
                type="checkbox"
                checked={categories.includes(category)}
                onChange={(event) =>
                  changeFilters(() =>
                    setCategories((current) => toggled(current, category, event.target.checked)),
                  )
                }
              />
              {category}
            </label>
          ))}
        </fieldset>
      </div>

      {isLoading && <StatePanel variant="loading" title="Loading complaints…" />}

      {!isLoading && error && (
        <StatePanel variant="error" title="Could not load complaints" description={error} />
      )}

      {!isLoading && !error && complaints.length === 0 && (
        <StatePanel
          title={hasFilters ? 'No complaints match these filters' : EMPTY_MESSAGES[view].title}
          description={
            hasFilters
              ? 'Try other categories or stages, or clear the filters.'
              : EMPTY_MESSAGES[view].description
          }
        />
      )}

      {!isLoading && !error && complaints.length > 0 && groupBy !== 'none' && (
        <div className="card-stack">
          {groupComplaints(complaints, groupBy).map((group) => (
            <section key={group.key} className="panel complaint-group">
              <GroupHeading group={group} />
              <div className="card-stack">
                {group.complaints.map((complaint) => (
                  <ComplaintLifecycleCard
                    key={complaint.complaint_id}
                    complaint={complaint}
                    showCallLink
                    groupedBy={group.isCustomer ? 'customer' : 'call'}
                    onUpdated={handleUpdated}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {!isLoading && !error && complaints.length > 0 && groupBy === 'none' && (
        <div className="card-stack">
          {complaints.map((complaint) => (
            <ComplaintLifecycleCard
              key={complaint.complaint_id}
              complaint={complaint}
              showCallLink
              onUpdated={handleUpdated}
            />
          ))}
        </div>
      )}
    </section>
  )
}
