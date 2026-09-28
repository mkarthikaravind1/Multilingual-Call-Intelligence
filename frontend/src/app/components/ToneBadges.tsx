import { humanizeLabel } from '../format/text'
import { complaintStatusTone, sentimentTone } from '../format/tone'

export function ComplaintStatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge badge--${complaintStatusTone(status)}`}>{humanizeLabel(status)}</span>
  )
}

export function SentimentBadge({ label }: { label: string }) {
  return <span className={`badge badge--${sentimentTone(label)}`}>{humanizeLabel(label)}</span>
}
