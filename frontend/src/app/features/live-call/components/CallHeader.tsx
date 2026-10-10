import type { ReactNode } from 'react'

import type {
  CallMetadataViewModel,
} from '../types/view-models'

import type {
  LiveSocketStatus,
} from '../services/liveCallSocket'

import {
  formatAiStatus,
  formatCallDirection,
  formatCallPhase,
  formatLoggingStatus,
} from '../adapters/toViewModel'
import { useCallDirectory } from '../hooks/useCallDirectory'
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
  // Put the call on hold (true) or take it off hold.
  onSetHold?: (onHold: boolean) => void
  isChangingHold?: boolean
  // What the AI is doing with the call right now, and where its record
  // stands; shown beside the call's own status.
  aiStatus?: string | null
  loggingStatuses?: string[]
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
  onSetHold,
  isChangingHold = false,
  aiStatus = null,
  loggingStatuses = [],
  children,
}: CallHeaderProps) {
  const isActive = call?.status.toLowerCase() === 'active'
  const isOnHold = call?.phase === 'on_hold'
  const directory = useCallDirectory()
  const nameOf = (entries: typeof directory.locations, id: string | null) =>
    entries.find((entry) => entry.id === id)?.name ?? null
  // "Incoming · Chennai · Asha", or as much of it as was recorded.
  const takenBy = call
    ? [
        formatCallDirection(call.direction),
        call.locationName ?? nameOf(directory.locations, call.locationId),
        call.executiveName ?? nameOf(directory.executives, call.executiveUserId),
      ]
        .filter(Boolean)
        .join(' · ')
    : ''

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

        {call && isActive && onSetHold && (
          <button
            type="button"
            className="live-call__secondary-button"
            onClick={() => onSetHold(!isOnHold)}
            disabled={isChangingHold || isCompleting}
            aria-pressed={isOnHold}
            title={
              isOnHold
                ? 'Take the customer off hold'
                : 'While on hold, nothing is transcribed or analysed'
            }
          >
            {isOnHold ? 'Resume call' : 'Hold'}
          </button>
        )}

        <div className="live-call__header-status">
          {takenBy && <span className="live-call__taken-by">{takenBy}</span>}
          {call && (
            <span
              className={`live-call__call-status live-call__call-status--${
                call.phase ?? call.status.toLowerCase()
              }`}
              title="Call status"
            >
              {formatCallPhase(call.phase, call.status)}
            </span>
          )}
          {aiStatus && (
            <span
              className={`live-call__ai-status live-call__ai-status--${aiStatus}`}
              title="What the AI is doing now"
            >
              <span className="live-call__ai-status-dot" aria-hidden="true" />
              AI: {formatAiStatus(aiStatus)}
            </span>
          )}
          {loggingStatuses.map((status) => (
            <span
              key={status}
              className={`live-call__logging-status live-call__logging-status--${status}`}
              title="Call record"
            >
              {formatLoggingStatus(status)}
            </span>
          ))}

          <ConnectionStatus
            status={connectionStatus}
          />
        </div>
      </div>

      {children}
    </section>
  )
}
