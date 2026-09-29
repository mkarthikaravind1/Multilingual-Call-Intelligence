import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { toUserErrorMessage } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { CustomerPanel } from '../features/customer/components/CustomerPanel'
import { EscalationCard } from '../features/escalation/components/EscalationCard'
import { useAuth } from '../auth/useAuth'
import type { EscalationViewModel } from '../features/escalation/types/view-models'
import { callRestService } from '../features/live-call/services/callRestService'
import { CallHeader } from '../features/live-call/components/CallHeader'
import { ComplaintPanel } from '../features/live-call/components/ComplaintPanel'
import { NextQuestionPanel } from '../features/live-call/components/NextQuestionPanel'
import { OtherFeaturesPanel } from '../features/live-call/components/OtherFeaturesPanel'
import { ToneIndicator } from '../features/live-call/components/ToneIndicator'
import { TranscriptPanel } from '../features/live-call/components/TranscriptPanel'
import { useLiveCall } from '../features/live-call/hooks/useLiveCall'

function newestEscalation(
  ...candidates: (EscalationViewModel | null)[]
): EscalationViewModel | null {
  return candidates.reduce<EscalationViewModel | null>(
    (newest, candidate) =>
      candidate && (!newest || candidate.updatedAt > newest.updatedAt) ? candidate : newest,
    null,
  )
}

export function LiveCallPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const callId = searchParams.get('call_id')?.trim() ?? ''
  const { session } = useAuth()
  const canManageEscalations =
    session?.role === 'SUPERVISOR' || session?.role === 'ADMIN'
  // A supervisor's acknowledge/resolve, shown until the next poll catches up.
  const [savedEscalation, setSavedEscalation] = useState<EscalationViewModel | null>(null)

  const liveCall = useLiveCall(callId || null)

  const {
    clearCall: clearLiveCall,
  } = liveCall

  const openCall = useCallback(
    (requestedCallId: string) => {
      const normalizedCallId = requestedCallId.trim()

      if (!normalizedCallId) {
        return
      }

      setSearchParams({
        call_id: normalizedCallId,
      })
    },
    [setSearchParams],
  )

  const clearCall = useCallback(() => {
  setSearchParams({})
  clearLiveCall()
}, [setSearchParams, clearLiveCall])

  const [isStarting, setIsStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  const startNewCall = useCallback(async () => {
    setIsStarting(true)
    setStartError(null)

    try {
      const created = await callRestService.startManualCall()
      setSearchParams({ call_id: created.call_id })
    } catch (err) {
      setStartError(toUserErrorMessage(err, 'Unable to start a new call.'))
    } finally {
      setIsStarting(false)
    }
  }, [setSearchParams])

  return (
    <section className="page-shell live-call-page">
      <CallHeader
        key={callId || 'empty'}
        call={liveCall.call}
        connectionStatus={liveCall.connectionStatus}
        isLoading={liveCall.isLoading}
        isCompleting={liveCall.isCompleting}
        initialCallId={callId}
        isStarting={isStarting}
        onStartCall={() => {
          void startNewCall()
        }}
        onOpenCall={openCall}
        onClearCall={clearCall}
        onCompleteCall={() => {
          void liveCall.completeCall()
        }}
      />

      {liveCall.error && (
        <div
          className="live-call__error"
          role="alert"
        >
          <strong>Live call issue</strong>
          <span>{liveCall.error}</span>
        </div>
      )}

      {startError && (
        <div
          className="live-call__error"
          role="alert"
        >
          <strong>Could not start a call</strong>
          <span>{startError}</span>
        </div>
      )}

      {!callId && (
        <div className="live-call__setup panel">
          <div>
            <p className="panel__label">
              No call selected
            </p>

            <h3>
              Open or start a call
            </h3>

            <p>
              Enter a call ID above to open an existing call, or start
              a new manual call. Telephony calls can be opened from
              Call History.
            </p>
          </div>
        </div>
      )}

      {callId && liveCall.isLoading && !liveCall.call && (
        <StatePanel
          variant="loading"
          title={`Opening call ${callId}`}
          description="Loading the conversation and connecting to the live intelligence stream."
        />
      )}

      {callId && liveCall.call && (
        <>
          <div className="live-call__workspace-grid">
            <div className="live-call__main-column">
              <TranscriptPanel
                transcript={liveCall.transcript}
              />
            </div>

            <aside className="live-call__side-column">
              <EscalationCard
                key={callId}
                escalation={newestEscalation(
                  liveCall.analysis?.escalation ?? null,
                  savedEscalation?.callId === callId ? savedEscalation : null,
                )}
                isCallActive={liveCall.call.status.toLowerCase() === 'active'}
                canManage={canManageEscalations}
                onUpdated={setSavedEscalation}
              />

              <CustomerPanel callId={callId} />

              <NextQuestionPanel
                suggestion={
                  liveCall.analysis?.questionSuggestion ?? null
                }
              />

              <ComplaintPanel
                complaints={
                  liveCall.analysis?.complaints ?? []
                }
              />

              <ToneIndicator
                sentiment={
                  liveCall.analysis?.sentiment ?? null
                }
              />
            </aside>
          </div>

          <OtherFeaturesPanel
            callId={callId}
            serviceEstimate={
              liveCall.analysis?.serviceEstimate ?? null
            }
          />
        </>
      )}
    </section>
  )
}