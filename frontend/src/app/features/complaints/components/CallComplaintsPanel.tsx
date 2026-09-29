import { useEffect, useState } from 'react'

import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import { complaintRestService } from '../services/complaintRestService'
import { ComplaintLifecycleCard } from './ComplaintLifecycleCard'

import type { CallComplaintsDto, ComplaintDto } from '../types/dto'

type CallComplaintsPanelProps = {
  callId: string
  isCallActive: boolean
  // Changes when the call changes state, so the panel reloads.
  refreshToken?: string
}

// This call's complaints through their lifecycle, and the same customer's
// complaints from earlier calls.
export function CallComplaintsPanel({
  callId,
  isCallActive,
  refreshToken,
}: CallComplaintsPanelProps) {
  const [data, setData] = useState<CallComplaintsDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showAllHistory, setShowAllHistory] = useState(false)

  useEffect(() => {
    let cancelled = false
    complaintRestService
      .getCallComplaints(callId)
      .then((response) => {
        if (!cancelled) {
          setData(response)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Unable to load complaints.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [callId, refreshToken])

  const replace = (updated: ComplaintDto) => {
    const swap = (items: ComplaintDto[]) =>
      items.map((item) => (item.complaint_id === updated.complaint_id ? updated : item))
    setData((current) =>
      current
        ? {
            ...current,
            complaints: swap(current.complaints),
            customer_history: swap(current.customer_history),
          }
        : current,
    )
  }

  const history = data?.customer_history ?? []
  const openHistory = history.filter((item) => item.is_open)
  const visibleHistory = showAllHistory ? history : openHistory

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="panel__label">Complaint lifecycle</p>
          <h3 className="section-title">Complaints on this call</h3>
        </div>
      </div>

      {error && <StatePanel compact variant="error" title="Could not load complaints" description={error} />}

      {!error && !data && <StatePanel compact variant="loading" title="Loading complaints…" />}

      {data && (
        <div className="card-stack">
          {data.complaints.length === 0 ? (
            <StatePanel
              compact
              title="No complaints"
              description={
                isCallActive
                  ? 'Complaints appear here as soon as they are detected in the conversation.'
                  : 'No complaint was detected on this call.'
              }
            />
          ) : (
            data.complaints.map((complaint) => (
              <ComplaintLifecycleCard
                key={complaint.complaint_id}
                complaint={complaint}
                onUpdated={replace}
              />
            ))
          )}

          <div className="section-heading spaced-top">
            <h4 className="complaint-panel__subtitle">Customer's earlier complaints</h4>
            {history.length > openHistory.length && (
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setShowAllHistory((current) => !current)}
              >
                {showAllHistory ? 'Show open only' : `Show all ${history.length}`}
              </button>
            )}
          </div>

          {data.customer_id === null ? (
            <p className="customer-panel__muted">
              Identify the customer to see their complaints from earlier calls.
            </p>
          ) : visibleHistory.length === 0 ? (
            <p className="customer-panel__muted">
              {history.length === 0
                ? 'No complaints on earlier calls.'
                : 'All of this customer’s earlier complaints are resolved.'}
            </p>
          ) : (
            visibleHistory.map((complaint) => (
              <ComplaintLifecycleCard
                key={complaint.complaint_id}
                complaint={complaint}
                showCallLink
                compact
                onUpdated={replace}
              />
            ))
          )}
        </div>
      )}
    </section>
  )
}
