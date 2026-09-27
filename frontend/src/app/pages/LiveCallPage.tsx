import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

import { CallHeader } from '../features/live-call/components/CallHeader'
import { ComplaintPanel } from '../features/live-call/components/ComplaintPanel'
import { NextQuestionPanel } from '../features/live-call/components/NextQuestionPanel'
import { OtherFeaturesPanel } from '../features/live-call/components/OtherFeaturesPanel'
import { ToneIndicator } from '../features/live-call/components/ToneIndicator'
import { TranscriptPanel } from '../features/live-call/components/TranscriptPanel'
import { useLiveCall } from '../features/live-call/hooks/useLiveCall'

export function LiveCallPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const callId = searchParams.get('call_id')?.trim() ?? ''

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

  return (
    <section className="page-shell live-call-page">
      <CallHeader
        key={callId || 'empty'}
        call={liveCall.call}
        connectionStatus={liveCall.connectionStatus}
        isLoading={liveCall.isLoading}
        isCompleting={liveCall.isCompleting}
        initialCallId={callId}
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

      {!callId && (
        <div className="live-call__setup panel">
          <div>
            <p className="panel__label">
              No call selected
            </p>

            <h3>
              Connect to an existing call
            </h3>

            <p>
              Enter a call ID above to load its current
              conversation and connect to the authenticated
              live intelligence stream.
            </p>
          </div>
        </div>
      )}

      {callId && liveCall.call && (
        <>
          <div className="live-call__workspace-grid">
            <div className="live-call__main-column">
              <TranscriptPanel
                transcript={liveCall.transcript}
              />

              <NextQuestionPanel
                suggestion={
                  liveCall.analysis?.questionSuggestion ?? null
                }
              />
            </div>

            <aside className="live-call__side-column">
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