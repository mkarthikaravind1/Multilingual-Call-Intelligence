import {
  useState,
} from 'react'

import type { FormEvent, ReactNode } from 'react'

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
  initialCallId: string
  onStartCall: () => void
  onOpenCall: (callId: string) => void
  onClearCall: () => void
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
  initialCallId,
  onStartCall,
  onOpenCall,
  onClearCall,
  onCompleteCall,
  children,
}: CallHeaderProps) {
  const [callIdInput, setCallIdInput] =
    useState(initialCallId)

  const handleSubmit = (
    event: FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault()
    onOpenCall(callIdInput)
  }

  const canComplete =
    Boolean(call) &&
    call?.status.toLowerCase() === 'active' &&
    !isLoading &&
    !isCompleting

  return (
    <section className="live-call__header panel">
      <form
        className="live-call__call-selector"
        onSubmit={handleSubmit}
      >
        <label htmlFor="live-call-id">
          Call ID
        </label>

        <input
          id="live-call-id"
          value={callIdInput}
          onChange={(event) =>
            setCallIdInput(
              event.target.value,
            )
          }
          placeholder="Enter an existing call ID"
          autoComplete="off"
        />

        <button
          type="submit"
          disabled={
            isLoading ||
            !callIdInput.trim()
          }
        >
          {isLoading
            ? 'Loading…'
            : 'Open call'}
        </button>

        {!call && (
          <button
            type="button"
            className="live-call__secondary-button"
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
            onClick={onCompleteCall}
            disabled={isCompleting}
          >
            {isCompleting
              ? 'Completing…'
              : 'Complete call'}
          </button>
        )}

        {call && (
          <button
            type="button"
            className="live-call__secondary-button"
            onClick={onClearCall}
          >
            Clear
          </button>
        )}

        <div className="live-call__header-status">
          <span
            className={`live-call__call-status live-call__call-status--${
              call?.status?.toLowerCase() ??
              'idle'
            }`}
          >
            {call?.status ??
              'No call selected'}
          </span>

          <ConnectionStatus
            status={connectionStatus}
          />
        </div>
      </form>

      {children}
    </section>
  )
}
