import type {
  ServiceEstimateViewModel,
} from '../types/view-models'

type ServiceEstimatePanelProps = {
  estimate: ServiceEstimateViewModel | null
  emptyMessage?: string
  // False when the surrounding panel already has a heading.
  showTitle?: boolean
}

// Every service that came up in the call so far, each priced from the
// price list, and their total. Amounts are the backend's Decimal strings,
// displayed as-is.
export function ServiceEstimatePanel({
  estimate,
  emptyMessage = 'No estimate for this call yet.',
  showTitle = true,
}: ServiceEstimatePanelProps) {
  return (
    <div className="live-call__reserved-card">
      <span className="live-call__reserved-icon" aria-hidden="true">
        {estimate ? '≈' : '—'}
      </span>

      <div>
        {showTitle && (
          <strong>
            Service &amp; cost estimate
          </strong>
        )}

        {estimate ? (
          <div className="info-list">
            {estimate.services.map((service) => (
              <div key={service.serviceName} className="service-estimate__service">
                <strong>
                  {service.serviceName}: {service.estimatedCost} {estimate.currency}
                </strong>
                {service.parts.map((part) => (
                  <span key={part.name}>
                    Part: {part.name} × {part.quantity} @ {part.unitPrice}{' '}
                    = {part.totalPrice} {estimate.currency}
                  </span>
                ))}
                <span>
                  Labour: {service.labour.hours} h @ {service.labour.hourlyRate}{' '}
                  = {service.labour.totalCost} {estimate.currency}
                </span>
                <span>Duration: {service.estimatedDurationHours} h</span>
              </div>
            ))}

            <div className="service-estimate__total">
              <span>Parts cost: {estimate.partsCost} {estimate.currency}</span>
              <span>Labour cost: {estimate.labourCost} {estimate.currency}</span>
              <span>Estimated duration: {estimate.estimatedDurationHours} h</span>
              <strong>
                Estimated cost
                {estimate.services.length > 1
                  ? ` (${estimate.services.length} services)`
                  : ''}
                : {estimate.estimatedCost} {estimate.currency}
              </strong>
            </div>
          </div>
        ) : (
          <span>{emptyMessage}</span>
        )}
      </div>
    </div>
  )
}
