import { useEffect, useState } from 'react'

import { ApiError } from '../../../api/errors'
import { RecordTime } from '../../../components/RecordTime'
import { StatePanel } from '../../../components/StatePanel'
import { customerRestService } from '../services/customerRestService'

import type { CallSummaryDeliveriesDto, SummaryDeliveryDto } from '../types/dto'

type SummaryDeliveryPanelProps = {
  callId: string
  isCallActive: boolean
  // Changes when the post-call summary appears, so the list is re-read.
  refreshToken?: string
}

const STATUS_LABELS: Record<SummaryDeliveryDto['status'], { label: string; badge: string }> = {
  sent: { label: 'Sent to gateway', badge: 'badge--success' },
  queued: { label: 'Queued', badge: 'badge--pending' },
  failed: { label: 'Failed', badge: 'badge--danger' },
  rejected: { label: 'Not sent', badge: 'badge--warning' },
}

const FAILURE_REASONS: Record<string, string> = {
  customer_consent_missing: 'The customer has not consented to receive summaries.',
  customer_not_eligible: 'The customer is not eligible to receive summaries.',
  provider_delivery_failed: 'The messaging gateway did not accept the message.',
}

export function SummaryDeliveryPanel({
  callId,
  isCallActive,
  refreshToken,
}: SummaryDeliveryPanelProps) {
  const [data, setData] = useState<CallSummaryDeliveriesDto | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    customerRestService
      .getSummaryDeliveries(callId)
      .then((response) => {
        if (!cancelled) {
          setData(response)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Unable to load summary delivery.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [callId, refreshToken])

  return (
    <article className="integration-card">
      <div className="integration-card__header">
        <strong>Customer summary delivery</strong>
        {data && !data.enabled && <span className="badge">Off</span>}
      </div>

      {error && <StatePanel compact variant="error" title="Could not load delivery" description={error} />}

      {!error && !data && <span className="customer-panel__muted">Loading…</span>}

      {data && !data.enabled && (
        <p>Summaries are not sent to customers: delivery is turned off in the backend configuration.</p>
      )}

      {data && data.enabled && data.deliveries.length === 0 && (
        <p>
          {isCallActive
            ? 'The summary is texted to the customer when the call is completed.'
            : 'No summary was sent for this call. The customer may not be identified, or no summary was generated.'}
        </p>
      )}

      {data?.deliveries.map((delivery) => {
        const status = STATUS_LABELS[delivery.status]
        const reason = delivery.failure_reason
          ? FAILURE_REASONS[delivery.failure_reason] ?? delivery.failure_reason
          : null

        return (
          <div key={delivery.delivery_id} className="customer-panel__body">
            <div className="list-card__meta">
              <span className={`badge ${status.badge}`}>{status.label}</span>
              <span className="badge">{delivery.channel === 'sms' ? 'SMS' : 'WhatsApp'}</span>
            </div>
            <span className="customer-panel__muted">
              <RecordTime seconds={delivery.created_at} />
              {delivery.provider_message_id && ` · Gateway ID ${delivery.provider_message_id}`}
            </span>
            {reason && <p>{reason}</p>}
            {delivery.status === 'failed' && delivery.last_error && (
              <span className="customer-panel__muted">{delivery.last_error}</span>
            )}
            <p className="summary-delivery__message">{delivery.message}</p>
          </div>
        )
      })}
    </article>
  )
}
