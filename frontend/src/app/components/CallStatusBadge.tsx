import { humanizeLabel } from '../format/text'

type CallStatusBadgeProps = {
  status: string
}

export function CallStatusBadge({ status }: CallStatusBadgeProps) {
  const normalized = status.toLowerCase()
  const modifier =
    normalized === 'active' ? 'active' : normalized === 'completed' ? 'completed' : 'neutral'

  return <span className={`badge badge--${modifier}`}>{humanizeLabel(status)}</span>
}
