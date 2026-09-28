import { Link } from 'react-router-dom'

type PostCallSummaryLinkProps = {
  callId?: string | null
}

export function PostCallSummaryLink({
  callId,
}: PostCallSummaryLinkProps) {
  const to = callId
    ? `/post-call-analysis?call_id=${encodeURIComponent(callId)}`
    : '/post-call-analysis'

  return (
    <div className="live-call__reserved-card">
      <span className="live-call__reserved-icon" aria-hidden="true">
        ↗
      </span>

      <div>
        <strong>
          Post-call summary
        </strong>

        <span>
          Generated automatically when the call is completed, together
          with the final complaint coverage and service estimate.
        </span>

        <Link to={to}>
          Open post-call analysis
        </Link>
      </div>
    </div>
  )
}
