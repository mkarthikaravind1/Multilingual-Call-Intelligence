import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { toUserErrorMessage } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { EscalationCard } from '../features/escalation/components/EscalationCard'
import { useAuth } from '../auth/useAuth'
import { useKeepSessionAlive } from '../auth/useKeepSessionAlive'
import type { EscalationViewModel } from '../features/escalation/types/view-models'
import { callRestService } from '../features/live-call/services/callRestService'
import { CallHeader } from '../features/live-call/components/CallHeader'
import { AlertsPanel } from '../features/live-call/components/AlertsPanel'
import { ComplaintPanel } from '../features/live-call/components/ComplaintPanel'
import { NextQuestionPanel } from '../features/live-call/components/NextQuestionPanel'
import { RecordingPanel } from '../features/live-call/components/RecordingPanel'
import { ServiceEstimatePanel } from '../features/live-call/components/ServiceEstimatePanel'
import { ToneIndicator } from '../features/live-call/components/ToneIndicator'
import { TranscriptPanel } from '../features/live-call/components/TranscriptPanel'
import { useLiveCall } from '../features/live-call/hooks/useLiveCall'
import { LIVE_SESSION_PARAM, isCallDetailsView } from '../features/live-call/liveCallMode'
import { TestAudioPanel } from '../features/test-audio/components/TestAudioPanel'
import { useTestAudioReplay } from '../features/test-audio/hooks/useTestAudioReplay'

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
  const isLiveSession = Boolean(callId) && !isCallDetailsView(searchParams)
  const { session } = useAuth()
  const canManageEscalations =
    session?.role === 'SUPERVISOR' || session?.role === 'ADMIN'
  // A supervisor's acknowledge/resolve, shown until the next poll catches up.
  const [savedEscalation, setSavedEscalation] = useState<EscalationViewModel | null>(null)

  const liveCall = useLiveCall(callId || null)

  // Shows a call started on this page: a manual call or a test-audio call.
  const openLiveCall = useCallback(
    (startedCallId: string) => {
      setSearchParams({ call_id: startedCallId, [LIVE_SESSION_PARAM]: '1' })
    },
    [setSearchParams],
  )

  const testAudio = useTestAudioReplay(openLiveCall)

  // A call in progress (or a test recording still playing) must never be
  // cut off by the session timing out.
  useKeepSessionAlive(
    liveCall.call?.status.toLowerCase() === 'active' ||
      ['preparing', 'streaming', 'ending'].includes(testAudio.phase),
  )

  const [isStarting, setIsStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  const startNewCall = useCallback(async () => {
    setIsStarting(true)
    setStartError(null)

    try {
      const created = await callRestService.startManualCall()
      openLiveCall(created.call_id)
    } catch (err) {
      setStartError(toUserErrorMessage(err, 'Unable to start a new call.'))
    } finally {
      setIsStarting(false)
    }
  }, [openLiveCall])

  return (
    <section className="page-shell live-call-page">
      <CallHeader
        key={callId || 'empty'}
        call={liveCall.call}
        connectionStatus={liveCall.connectionStatus}
        isLoading={liveCall.isLoading}
        isCompleting={liveCall.isCompleting}
        isStarting={isStarting}
        isLiveSession={isLiveSession}
        onStartCall={() => {
          void startNewCall()
        }}
        onCompleteCall={() => {
          void liveCall.completeCall()
        }}
        onSetHold={(onHold) => {
          void liveCall.setOnHold(onHold)
        }}
        isChangingHold={liveCall.isChangingHold}
        aiStatus={liveCall.analysis?.aiStatus ?? null}
        loggingStatuses={liveCall.analysis?.loggingStatuses ?? []}
      >
        {canManageEscalations && <TestAudioPanel replay={testAudio} />}
      </CallHeader>


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
            <h3>
              Before you start a call
            </h3>

            <ul className="live-call__tips">
              <li>
                Use a headset or a good-quality microphone; clear audio gives
                a more accurate transcript.
              </li>
              <li>
                Take the call somewhere quiet, and let one person speak at a
                time.
              </li>
              <li>
                Press <strong>Start new call</strong> when the conversation
                begins. The transcript, complaints, tone and suggested
                questions update live as you talk.
              </li>
              <li>
                Press <strong>Complete call</strong> when it ends to get the
                post-call summary.
              </li>
            </ul>
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
          <div className="live-call__workspace-grid live-call__workspace-grid--live">
            <div className="live-call__main-column">
              <TranscriptPanel
                transcript={liveCall.transcript}
              />
            </div>

            <aside className="live-call__side-column">
              <AlertsPanel
                alerts={liveCall.analysis?.alerts ?? []}
                isCallActive={liveCall.call.status.toLowerCase() === 'active'}
              />

              <NextQuestionPanel
                suggestions={liveCall.analysis?.questionSuggestions ?? []}
                callId={callId}
                isCallActive={liveCall.call.status.toLowerCase() === 'active'}
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
                compact
              />

              <EscalationCard
                key={callId}
                escalation={newestEscalation(
                  liveCall.analysis?.escalation ?? null,
                  savedEscalation?.callId === callId ? savedEscalation : null,
                )}
                isCallActive={liveCall.call.status.toLowerCase() === 'active'}
                canManage={canManageEscalations}
                compact
                onUpdated={setSavedEscalation}
              />

              {canManageEscalations && liveCall.call.status.toLowerCase() !== 'active' && (
                <RecordingPanel key={`recording-${callId}`} callId={callId} />
              )}

              <section className="panel">
                <h4 className="live-call__panel-title">Service estimate</h4>
                <ServiceEstimatePanel
                  estimate={liveCall.analysis?.serviceEstimate ?? null}
                  showTitle={false}
                />
              </section>
            </aside>
          </div>
        </>
      )}
    </section>
  )
}