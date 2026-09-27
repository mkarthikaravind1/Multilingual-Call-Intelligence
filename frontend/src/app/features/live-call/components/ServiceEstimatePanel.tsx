import type {
  ServiceEstimateViewModel,
} from '../types/view-models'

type ServiceEstimatePanelProps = {
  estimate: ServiceEstimateViewModel | null
}

// Amounts are the backend's Decimal strings, displayed as-is.
export function ServiceEstimatePanel({
  estimate,
}: ServiceEstimatePanelProps) {
  return (
    <div className="live-call__reserved-card">
      <span className="live-call__reserved-icon">
        {estimate ? '≈' : '—'}
      </span>

      <div>
        <strong>
          Service &amp; cost estimate
        </strong>

        {estimate ? (
          <div className="info-list">
            <span>Service: {estimate.serviceName}</span>
            <span>
              Estimated duration: {estimate.estimatedDurationHours} h
            </span>

            {estimate.parts.map((part) => (
              <span key={part.name}>
                Part: {part.name} × {part.quantity} @ {part.unitPrice}{' '}
                = {part.totalPrice} {estimate.currency}
              </span>
            ))}

            <span>
              Labour: {estimate.labour.hours} h @ {estimate.labour.hourlyRate}{' '}
              = {estimate.labour.totalCost} {estimate.currency}
            </span>
            <span>Parts cost: {estimate.partsCost} {estimate.currency}</span>
            <span>Labour cost: {estimate.labourCost} {estimate.currency}</span>
            <strong>
              Estimated cost: {estimate.estimatedCost} {estimate.currency}
            </strong>
          </div>
        ) : (
          <span>No estimate for this call yet.</span>
        )}
      </div>
    </div>
  )
}
