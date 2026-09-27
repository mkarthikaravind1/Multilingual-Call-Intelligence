import { useState } from 'react'

import { EscalationStatus } from './EscalationStatus'
import { PostCallSummaryLink } from './PostCallSummaryLink'
import { ServiceEstimatePanel } from './ServiceEstimatePanel'
import { VehicleInfoPanel } from './VehicleInfoPanel'

type OtherFeaturesPanelProps = {
  callId?: string | null
}

export function OtherFeaturesPanel({
  callId,
}: OtherFeaturesPanelProps) {
  const [isOpen, setIsOpen] =
    useState(false)

  return (
    <section className="panel live-call__other-panel">
      <button
        type="button"
        className="live-call__other-toggle"
        onClick={() =>
          setIsOpen(
            (current) => !current,
          )
        }
        aria-expanded={isOpen}
      >
        <span>
          <span className="panel__label">
            Other features
          </span>

          <strong>
            Future integrations
          </strong>
        </span>

        <span
          className="live-call__toggle-icon"
          aria-hidden="true"
        >
          {isOpen ? '−' : '+'}
        </span>
      </button>

      {isOpen && (
        <div className="live-call__reserved-list">
          <EscalationStatus />
          <ServiceEstimatePanel />
          <VehicleInfoPanel />
          <PostCallSummaryLink callId={callId} />
        </div>
      )}
    </section>
  )
}