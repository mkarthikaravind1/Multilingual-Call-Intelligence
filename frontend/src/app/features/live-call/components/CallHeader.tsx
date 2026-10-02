import type { ReactNode } from 'react'

import type {
  CallMetadataViewModel,
} from '../types/view-models'

import type {
  LiveSocketStatus,
} from '../services/liveCallSocket'

import { ConnectionStatus } from './ConnectionStatus'

type CallHeaderProps = {
  call: CallMetadataViewModel | null
  connectionStatus: LiveSocketStatus
  isLoading: boolean
  isCompleting: boolean
  isStarting: boolean
  // True while showing a call started from this page (not one opened
  // from a call list), so it can be completed before starting another.
  isLiveSession: boolean
  onStartCall: () => void
  onCompleteCall: () => void
  // Extra controls shown in the same box (e.g. test audio).
  children?: ReactNode
}

export function CallHeader({
  call,
  connectionStatus,
  isLoading,
  isCompleting,
  isStarting,
  isLiveSession,
  onStartCall,
  onCompleteCall,
  children,
}: CallHeaderProps) {
  const isActive = call?.status.toLowerCase() === 'active'

  const canComplete =
    Boolean(call) &&
    isActive &&
    !isLoading &&
    !isCompleting

  // A call in progress on this page is completed first; otherwise
  // (no call, a finished one, or one opened from a list) a new one can start.
  const canStartNew = !(isLiveSession && isActive)

  return (
    <section className="live-call__header panel">
      <div className="live-call__call-selector">
        {canStartNew && (
          <button
            type="button"
            onClick={onStartCall}
            disabled={isStarting || isLoading}
          >
            {isStarting
              ? 'Starting…'
              : 'Start new call'}
          </button>
        )}

        {canComplete && (
          <button
            type="button"
            className={canStartNew ? 'live-call__secondary-button' : undefined}
            onClick={onCompleteCall}
            disabled={isCompleting}
          >
            {isCompleting
              ? 'Completing…'
              : 'Complete call'}
          </button>
        )}

        <div className="live-call__header-status">
          {call && (
            <span
              className={`live-call__call-status live-call__call-status--${call.status.toLowerCase()}`}
            >
              {call.status}
            </span>
          )}

          <ConnectionStatus
            status={connectionStatus}
          />
        </div>
      </div>

      {children}
    </section>
  )
}
