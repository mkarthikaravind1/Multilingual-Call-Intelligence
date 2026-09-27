import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { formatUnixTimestamp } from '../format/time'

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
import { ServiceEstimatePanel } from '../features/live-call/components/ServiceEstimatePanel'
import { ToneIndicator } from '../features/live-call/components/ToneIndicator'
import { TranscriptPanel } from '../features/live-call/components/TranscriptPanel'

import type {
  CallAnalysisViewModel,
  CallMetadataViewModel,
  TranscriptTurnViewModel,
} from '../features/live-call/types/view-models'

export function PostCallAnalysisPage() {
  const [searchParams] = useSearchParams()

  const callId = searchParams.get('call_id')?.trim() ?? ''

  const [call, setCall] = useState<CallMetadataViewModel | null>(null)
  const [analysis, setAnalysis] = useState<CallAnalysisViewModel | null>(null)
  const [utterances, setUtterances] = useState<TranscriptTurnViewModel[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isCompleting, setIsCompleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  const handleCompleteCall = async () => {
    if (!callId || !call || call.status.toLowerCase() !== 'active') {
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

  const isActiveCall =
    call?.status.toLowerCase() === 'active'

  return (
    <section className="page-shell">
      <div className="page-shell__header">
        <div>
          <p className="eyebrow">Analysis</p>
          <h2>Post-call analysis</h2>
        </div>
      </div>

      {!callId && (
        <div className="panel">
          <p className="panel__label">No call selected</p>
          <p>
            Add a call ID to the URL as{' '}
            <code>?call_id=&lt;call_id&gt;</code> to view its analysis.
          </p>
        </div>
      )}

      {callId && isLoading && (
        <div className="panel">
          <p>Loading call {callId}…</p>
        </div>
      )}

      {callId && !isLoading && error && (
        <div className="live-call__error" role="alert">
          <strong>Could not load post-call analysis</strong>
          <span>{error}</span>
        </div>
      )}

      {callId && !isLoading && !error && call && analysis && (
        <>
          <div className="panel">
            <div className="page-shell__header">
              <div>
                <p className="panel__label">Call {call.callId}</p>
                <div className="info-list">
                  <span>Status: {call.status}</span>
                  <span>Start time: {formatUnixTimestamp(call.startTime)}</span>
                  <span>
                    End time: {call.endTime != null ? formatUnixTimestamp(call.endTime) : '—'}
                  </span>
                  <span>
                    Utterance count: {call.utteranceCount}
                  </span>
                </div>
              </div>

              {isActiveCall && (
                <button
                  type="button"
                  onClick={() => void handleCompleteCall()}
                  disabled={isCompleting}
                >
                  {isCompleting ? 'Completing…' : 'Complete Call'}
                </button>
              )}
            </div>
          </div>

          <div className="live-call__workspace-grid">
            <TranscriptPanel transcript={utterances} />

            <ComplaintPanel
              complaints={analysis.complaints}
            />

            <ToneIndicator sentiment={analysis.sentiment} />

            <NextQuestionPanel
              suggestion={analysis.questionSuggestion}
            />
          </div>

          <div className="panel">
            <ServiceEstimatePanel estimate={analysis.serviceEstimate} />
          </div>

          {analysis.postCallSummary && (
            <div className="panel">
              <p className="panel__label">Post-call summary</p>
              <p>{analysis.postCallSummary.overallSummary}</p>

              <div className="info-list">
                <span>
                  Customer summary: {analysis.postCallSummary.customerSummary}
                </span>
                <span>
                  Languages: {analysis.postCallSummary.languages.join(', ')}
                </span>
                <span>
                  Sentiment: {analysis.postCallSummary.sentiment.label} (
                  {Math.round(analysis.postCallSummary.sentiment.confidence * 100)}%)
                </span>
                <span>
                  Follow-up required:{' '}
                  {analysis.postCallSummary.followUpRequired ? 'Yes' : 'No'}
                </span>
              </div>

              {analysis.postCallSummary.complaints.length > 0 && (
                <>
                  <p className="panel__label">Complaints</p>
                  <ul>
                    {analysis.postCallSummary.complaints.map((complaint) => (
                      <li key={complaint.category}>
                        {complaint.category} · {complaint.status}:{' '}
                        {complaint.description}
                        {complaint.confidence !== null &&
                          ` (${Math.round(complaint.confidence * 100)}%)`}
                        <br />
                        <small>Evidence: {complaint.evidence}</small>
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {analysis.postCallSummary.unresolvedIssues.length > 0 && (
                <>
                  <p className="panel__label">Unresolved issues</p>
                  <ul>
                    {analysis.postCallSummary.unresolvedIssues.map((issue) => (
                      <li key={issue}>{issue}</li>
                    ))}
                  </ul>
                </>
              )}

              {analysis.postCallSummary.actionsPromised.length > 0 && (
                <>
                  <p className="panel__label">Actions promised</p>
                  <ul>
                    {analysis.postCallSummary.actionsPromised.map((action) => (
                      <li key={action}>{action}</li>
                    ))}
                  </ul>
                </>
              )}

              {analysis.postCallSummary.serviceEstimate && (
                <ServiceEstimatePanel
                  estimate={analysis.postCallSummary.serviceEstimate}
                />
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}