import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { ComplaintLifecycleCard } from '../features/complaints/components/ComplaintLifecycleCard'
import { complaintRestService } from '../features/complaints/services/complaintRestService'

import type { ComplaintDto, ComplaintQueueState } from '../features/complaints/types/dto'

// Complaints from calls in progress appear without a manual refresh.
const REFRESH_INTERVAL_MS = 15000

const VIEWS: { value: ComplaintQueueState; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All' },
]

const EMPTY_MESSAGES: Record<ComplaintQueueState, { title: string; description: string }> = {
  open: {
    title: 'No open complaints',
    description:
      'Complaints appear here as soon as they are detected on a call. Those a call ended without resolving are flagged for follow-up and listed first.',
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

export function ComplaintsPage() {
  const [view, setView] = useState<ComplaintQueueState>('open')
  const [complaints, setComplaints] = useState<ComplaintDto[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (state: ComplaintQueueState) => {
    try {
      setComplaints(await complaintRestService.listQueue(state))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to load complaints.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const refresh = () => {
      if (!cancelled) {
        void load(view)
      }
    }
    refresh()
    const intervalId = window.setInterval(refresh, REFRESH_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [view, load])

  const switchView = (next: ComplaintQueueState) => {
    if (next !== view) {
      setIsLoading(true)
      setComplaints([])
      setView(next)
    }
  }

  const handleUpdated = (updated: ComplaintDto) => {
    setComplaints((current) =>
      (view === 'open' && !updated.is_open) || (view === 'resolved' && updated.is_open)
        ? current.filter((item) => item.complaint_id !== updated.complaint_id)
        : current.map((item) => (item.complaint_id === updated.complaint_id ? updated : item)),
    )
  }

  const followUps = complaints.filter((c) => c.is_open && c.follow_up_required).length

  return (
    <section className="page-shell">
      <div className="page-shell__header page-shell__header--actions">
        <div className="button-row" role="tablist" aria-label="Complaint queue">
          {VIEWS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={view === item.value}
              className={view === item.value ? 'button' : 'button button--secondary'}
              onClick={() => switchView(item.value)}
            >
              {item.label}
            </button>
          ))}
        </div>
        {view === 'open' && !isLoading && !error && (
          <span className="customer-panel__muted">
            {complaints.length} open · {followUps} need follow-up
          </span>
        )}
      </div>

      {isLoading && <StatePanel variant="loading" title="Loading complaints…" />}

      {!isLoading && error && (
        <StatePanel variant="error" title="Could not load complaints" description={error} />
      )}

      {!isLoading && !error && complaints.length === 0 && (
        <StatePanel
          title={EMPTY_MESSAGES[view].title}
          description={EMPTY_MESSAGES[view].description}
        />
      )}

      {!isLoading && !error && complaints.length > 0 && (
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
