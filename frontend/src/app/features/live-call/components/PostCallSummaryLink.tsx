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
      <span className="live-call__reserved-icon">
        ↗
      </span>

      <div>
        <strong>
          Post-call analysis
        </strong>

        <span>
          Detailed post-call data is not
          part of the current live analysis
          response.
        </span>

        <Link to={to}>
          Open post-call analysis
        </Link>
      </div>
    </div>
  )
}