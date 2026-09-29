import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { CallStatusBadge } from '../components/CallStatusBadge'
import { IntegrationPendingCard } from '../components/IntegrationPendingCard'
import { StatePanel } from '../components/StatePanel'
import { formatCallDuration } from '../format/time'

import { AiReviewPanel } from '../features/ai-improvement/components/AiReviewPanel'

import {
  toCallAnalysisViewModel,
  toCallMetadataViewModel,
  toTranscriptTurnViewModel,
} from '../features/live-call/adapters/toViewModel'

import {
  callRestService,
} from '../features/live-call/services/callRestService'

import { ComplaintPanel } from '../features/live-call/components/ComplaintPanel'
import { NextQuestionPanel } from '../features/live-call/components/NextQuestionPanel'
import {
  PostCallSummaryPanel,
  type PostCallSummaryState,
} from '../features/live-call/components/PostCallSummaryPanel'
import { ServiceEstimatePanel } from '../features/live-call/components/ServiceEstimatePanel'
import { ToneIndicator } from '../features/live-call/components/ToneIndicator'
import { TranscriptPanel } from '../features/live-call/components/TranscriptPanel'

import type {
  CallAnalysisViewModel,
  CallMetadataViewModel,
  TranscriptTurnViewModel,
} from '../features/live-call/types/view-models'

// The summary is generated right after completion (in the background for
// telephony calls), so a just-completed call is re-checked for a short while.
const SUMMARY_POLL_INTERVAL_MS = 3000
const SUMMARY_POLL_ATTEMPTS = 5

export function PostCallAnalysisPage() {
  const [searchParams] = useSearchParams()

  const callId = searchParams.get('call_id')?.trim() ?? ''

  const [call, setCall] = useState<CallMetadataViewModel | null>(null)
  const [analysis, setAnalysis] = useState<CallAnalysisViewModel | null>(null)
  const [utterances, setUtterances] = useState<TranscriptTurnViewModel[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isCompleting, setIsCompleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [summaryPollFinishedFor, setSummaryPollFinishedFor] = useState<string | null>(null)

  useEffect(() => {
    if (!callId) {
      return
    }

    let cancelled = false

    const loadData = async () => {
      setIsLoading(true)
      setError(null)

      try {
        const callResponse = await callRestService.getCall(callId)

        if (cancelled) {
          return
        }

        const analysisResponse = await callRestService.getAnalysis(callId)

        if (cancelled) {
          return
        }

        setCall(toCallMetadataViewModel(callResponse))
        setUtterances(
          callResponse.utterances.map(toTranscriptTurnViewModel),
        )
        setAnalysis(toCallAnalysisViewModel(analysisResponse))
      } catch (err) {
        if (cancelled) {
          return
        }

        setCall(null)
        setAnalysis(null)
        setUtterances([])

        if (err instanceof ApiError) {
          setError(err.message)
        } else {
          setError('Unable to load post-call analysis.')
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void loadData()

    return () => {
      cancelled = true
    }
  }, [callId])

  const isActiveCall = call?.status.toLowerCase() === 'active'
  const isCompletedCall = call?.status.toLowerCase() === 'completed'
  const hasSummary = Boolean(analysis?.postCallSummary)
  const hasSpeech = (call?.utteranceCount ?? 0) > 0

  const isWaitingForSummary =
    isCompletedCall &&
    Boolean(analysis) &&
    !hasSummary &&
    hasSpeech &&
    summaryPollFinishedFor !== callId

  useEffect(() => {
    if (!isWaitingForSummary) {
      return
    }

    let cancelled = false
    let attempts = 0

    const intervalId = window.setInterval(async () => {
      attempts += 1

      try {
        const analysisResponse = await callRestService.getAnalysis(callId)
        if (!cancelled) {
          setAnalysis(toCallAnalysisViewModel(analysisResponse))
        }
      } catch {
        // Keep showing the last successful analysis.
      }

      if (!cancelled && attempts >= SUMMARY_POLL_ATTEMPTS) {
        window.clearInterval(intervalId)
        setSummaryPollFinishedFor(callId)
      }
    }, SUMMARY_POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [callId, isWaitingForSummary])

  const handleCompleteCall = async () => {
    if (!callId || !isActiveCall) {
      return
    }

    setIsCompleting(true)
    setError(null)

    try {
      await callRestService.completeCall(callId, {
        end_time: Date.now() / 1000,
      })

      const callResponse = await callRestService.getCall(callId)
      const analysisResponse = await callRestService.getAnalysis(callId)

      setCall(toCallMetadataViewModel(callResponse))
      setUtterances(
        callResponse.utterances.map(toTranscriptTurnViewModel),
      )
      setAnalysis(toCallAnalysisViewModel(analysisResponse))
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Unable to complete the call.')
      }
    } finally {
      setIsCompleting(false)
    }
  }

  const summaryState: PostCallSummaryState = hasSummary
    ? 'available'
    : isActiveCall
      ? 'active_call'
      : !hasSpeech
        ? 'no_speech'
        : isWaitingForSummary
          ? 'generating'
          : 'unavailable'

  return (
    <section className="page-shell">
      {callId && (
        <div className="page-shell__header page-shell__header--actions">
          <Link className="button button--secondary" to="/call-history">
            Back to call history
          </Link>
        </div>
      )}

      {!callId && (
        <StatePanel
          title="No call selected"
          description="Choose a call from Call History to review its transcript, complaints, service estimate and post-call summary."
          action={
            <Link className="button" to="/call-history">
              Browse call history
            </Link>
          }
        />
      )}

      {callId && isLoading && (
        <StatePanel variant="loading" title={`Loading call ${callId}…`} />
      )}

      {callId && !isLoading && error && (
        <StatePanel
          variant="error"
          title={call ? 'Could not complete the call' : 'Could not load post-call analysis'}
          description={error}
        />
      )}

      {callId && !isLoading && call && analysis && (
        <>
          <div className="panel">
            <div className="section-heading">
              <div>
                <p className="panel__label">Call</p>
                <h3 className="section-title">{call.callId}</h3>
              </div>

              <div className="button-row">
                <CallStatusBadge status={call.status} />
                {isActiveCall && (
                  <button
                    type="button"
                    className="button"
                    onClick={() => void handleCompleteCall()}
                    disabled={isCompleting}
                  >
                    {isCompleting ? 'Completing…' : 'Complete call'}
                  </button>
                )}
              </div>
            </div>

            <div className="fact-grid">
              <div className="fact">
                <span>Duration</span>
                <strong>{formatCallDuration(call.startTime, call.endTime)}</strong>
              </div>
              <div className="fact">
                <span>Utterances</span>
                <strong>{call.utteranceCount}</strong>
              </div>
            </div>
          </div>

          <PostCallSummaryPanel
            state={summaryState}
            summary={analysis.postCallSummary}
          />

          <div className="live-call__workspace-grid">
            <div className="live-call__main-column">
              <TranscriptPanel transcript={utterances} />
            </div>

            <aside className="live-call__side-column">
              <section className="panel">
                <p className="panel__label">Service estimate</p>
                <ServiceEstimatePanel
                  estimate={analysis.serviceEstimate}
                  emptyMessage={
                    isActiveCall
                      ? 'No estimate for this call yet.'
                      : 'No service estimate was produced for this call.'
                  }
                />
              </section>
              <ComplaintPanel complaints={analysis.complaints} />
              <ToneIndicator sentiment={analysis.sentiment} />
              <NextQuestionPanel
                suggestion={analysis.questionSuggestion}
                emptyMessage={
                  isActiveCall
                    ? undefined
                    : 'Next-question suggestions are only generated while a call is active.'
                }
              />
            </aside>
          </div>

          <AiReviewPanel callId={call.callId} />

          <section className="panel">
            <p className="panel__label">Customer follow-up</p>
            <div className="integration-grid">
              <IntegrationPendingCard
                title="Customer summary delivery"
                description="SMS/WhatsApp delivery status will appear once a messaging provider and customer contact lookup are connected."
              />
              <IntegrationPendingCard
                title="Complaint history"
                description="The customer's previous complaints and their lifecycle will appear once calls are linked to customer records through CRM."
              />
              <IntegrationPendingCard
                title="Vehicle information"
                description="Vehicle information will appear once CRM integration is connected."
              />
            </div>
          </section>
        </>
      )}
    </section>
  )
}
