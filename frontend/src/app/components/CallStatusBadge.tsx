import { humanizeLabel } from '../format/text'

type CallStatusBadgeProps = {
  status: string
  // Where the call stands (incoming, outgoing, connected, on_hold,
  // ended), when the server says: shown instead of the plain status.
  phase?: string | null
}

export function CallStatusBadge({ status, phase }: CallStatusBadgeProps) {
  const normalized = status.toLowerCase()
  const modifier =
    phase === 'on_hold'
      ? 'warning'
      : normalized === 'active'
        ? 'active'
        : normalized === 'completed'
          ? 'completed'
          : 'neutral'

  return <span className={`badge badge--${modifier}`}>{humanizeLabel(phase ?? status)}</span>
}
