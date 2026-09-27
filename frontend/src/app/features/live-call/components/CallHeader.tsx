import {
  useState,
} from 'react'

import type { FormEvent } from 'react'

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
  initialCallId: string
  onOpenCall: (callId: string) => void
  onClearCall: () => void
  onCompleteCall: () => void
}

export function CallHeader({
  call,
  connectionStatus,
  isLoading,
  isCompleting,
  initialCallId,
  onOpenCall,
  onClearCall,
  onCompleteCall,
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
      <div className="live-call__header-main">
        <div>
          <p className="panel__label">
            Live call workspace
          </p>

          <h3>
            {call
              ? `Call ${call.callId}`
              : 'Open a live call'}
          </h3>

          <p className="live-call__header-meta">
            {call
              ? `${call.utteranceCount} recorded utterance${
                  call.utteranceCount === 1
                    ? ''
                    : 's'
                }`
              : 'Use an existing backend call ID to connect to the live intelligence stream.'}
          </p>
        </div>

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
      </div>

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
      </form>
    </section>
  )
}
