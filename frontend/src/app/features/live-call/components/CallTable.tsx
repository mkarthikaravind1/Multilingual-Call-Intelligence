import { Link } from 'react-router-dom'

import { CallStatusBadge } from '../../../components/CallStatusBadge'
import { EscalationLevelBadge } from '../../escalation/components/EscalationCard'
import { formatCallDuration, formatRecordTimestamp } from '../../../format/time'
import { formatCallDirection, formatCallerLabel } from '../adapters/toViewModel'
import type { CallMetadataViewModel } from '../types/view-models'

type CallTableProps = {
  calls: CallMetadataViewModel[]
}

export function CallTable({ calls }: CallTableProps) {
  return (
    <div className="panel panel--list call-table" role="table" aria-label="Calls">
      <div className="table-row table-row--calls table-row--head" role="row">
        <span role="columnheader">Caller</span>
        <span role="columnheader">Phone number</span>
        <span role="columnheader">Taken by</span>
        <span role="columnheader">Status</span>
        <span role="columnheader">Call date</span>
        <span role="columnheader">Resolved on</span>
        <span role="columnheader">Duration</span>
        <span role="columnheader">Utterances</span>
        <span role="columnheader">Open</span>
      </div>

      {calls.map((call) => (
        <div className="table-row table-row--calls" role="row" key={call.callId}>
          <span className="table-cell table-cell--primary" role="cell" title={call.callId}>
            {formatCallerLabel(call)}
          </span>
          <span className="table-cell table-cell--nowrap" role="cell" data-label="Phone number">
            {call.callerNumber ?? '—'}
          </span>
          <span className="table-cell call-table__taken-by" role="cell" data-label="Taken by">
            <span>{call.executiveName ?? 'Not recorded'}</span>
            <small>
              {[formatCallDirection(call.direction), call.locationName]
                .filter(Boolean)
                .join(' · ') || '—'}
            </small>
          </span>
          <span className="table-cell call-history__status" role="cell" data-label="Status">
            <CallStatusBadge status={call.status} />
            {call.escalationLevel && call.escalationStatus !== 'resolved' && (
              <EscalationLevelBadge level={call.escalationLevel} />
            )}
          </span>
          <span className="table-cell" role="cell" data-label="Call date">
            {formatRecordTimestamp(call.startTime)}
          </span>
          <span className="table-cell" role="cell" data-label="Resolved on">
            {call.complaintsResolvedAt == null
              ? '—'
              : formatRecordTimestamp(call.complaintsResolvedAt)}
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
              Call Transcript
            </Link>
            <Link
              className="call-history__link"
              to={`/post-call-analysis?call_id=${encodeURIComponent(call.callId)}`}
            >
              Post Call Analysis
            </Link>
          </span>
        </div>
      ))}
    </div>
  )
}
