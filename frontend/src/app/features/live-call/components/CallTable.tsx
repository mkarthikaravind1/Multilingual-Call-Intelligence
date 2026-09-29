import { Link } from 'react-router-dom'

import { CallStatusBadge } from '../../../components/CallStatusBadge'
import { EscalationLevelBadge } from '../../escalation/components/EscalationCard'
import { formatCallDuration } from '../../../format/time'
import type { CallMetadataViewModel } from '../types/view-models'

type CallTableProps = {
  calls: CallMetadataViewModel[]
}

export function CallTable({ calls }: CallTableProps) {
  return (
    <div className="panel panel--list" role="table" aria-label="Calls">
      <div className="table-row table-row--calls table-row--head" role="row">
        <span role="columnheader">Call ID</span>
        <span role="columnheader">Status</span>
        <span role="columnheader">Duration</span>
        <span role="columnheader">Utterances</span>
        <span role="columnheader">Open</span>
      </div>

      {calls.map((call) => (
        <div className="table-row table-row--calls" role="row" key={call.callId}>
          <span className="table-cell table-cell--primary" role="cell">
            {call.callId}
          </span>
          <span className="table-cell call-history__status" role="cell" data-label="Status">
            <CallStatusBadge status={call.status} />
            {call.escalationLevel && call.escalationStatus !== 'resolved' && (
              <EscalationLevelBadge level={call.escalationLevel} />
            )}
          </span>
          <span className="table-cell" role="cell" data-label="Duration">
            {formatCallDuration(call.startTime, call.endTime)}
          </span>
          <span className="table-cell" role="cell" data-label="Utterances">
            {call.utteranceCount}
          </span>
          <span className="table-cell call-history__actions" role="cell">
            <Link
              className="call-history__link"
              to={`/live-call?call_id=${encodeURIComponent(call.callId)}`}
            >
              Live Call
            </Link>
            <Link
              className="call-history__link"
              to={`/post-call-analysis?call_id=${encodeURIComponent(call.callId)}`}
            >
              Post-call Analysis
            </Link>
          </span>
        </div>
      ))}
    </div>
  )
}
