import type { LiveSocketStatus } from '../services/liveCallSocket'

type ConnectionStatusProps = {
  status: LiveSocketStatus
}

const STATUS_LABELS: Record<
  LiveSocketStatus,
  string
> = {
  disconnected: 'Disconnected',
  connecting: 'Connecting',
  connected: 'Live connection',
  reconnecting: 'Reconnecting',
  error: 'Connection issue',
  closed: 'Closed',
}

export function ConnectionStatus({
  status,
}: ConnectionStatusProps) {
  return (
    <div
      className={`live-call__connection live-call__connection--${status}`}
    >
      <span
        className="live-call__connection-dot"
        aria-hidden="true"
      />

      <span>
        {STATUS_LABELS[status]}
      </span>
    </div>
  )
}