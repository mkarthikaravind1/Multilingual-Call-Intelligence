import { useState } from 'react'

import { EscalationStatus } from './EscalationStatus'
import { PostCallSummaryLink } from './PostCallSummaryLink'
import { ServiceEstimatePanel } from './ServiceEstimatePanel'
import type { ServiceEstimateViewModel } from '../types/view-models'

type OtherFeaturesPanelProps = {
  callId?: string | null
  serviceEstimate?: ServiceEstimateViewModel | null
}

export function OtherFeaturesPanel({
  callId,
  serviceEstimate = null,
}: OtherFeaturesPanelProps) {
  const [isOpen, setIsOpen] =
    useState(true)

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
        aria-controls="live-call-insights"
      >
        <span>
          <span className="panel__label">
            Call insights
          </span>

          <strong>
            Estimate, summary &amp; escalation
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
        <div id="live-call-insights" className="live-call__reserved-list">
          <ServiceEstimatePanel estimate={serviceEstimate} />
          <PostCallSummaryLink callId={callId} />
          <EscalationStatus />
        </div>
      )}
    </section>
  )
}