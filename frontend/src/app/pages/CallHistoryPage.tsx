import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { callRestService } from '../features/live-call/services/callRestService'
import { toCallMetadataViewModel } from '../features/live-call/adapters/toViewModel'
import type { CallMetadataViewModel } from '../features/live-call/types/view-models'
import { ApiError } from '../api/errors'
import { formatUnixTimestamp } from '../format/time'

export function CallHistoryPage() {
  const [searchParams] = useSearchParams()
  const callId = searchParams.get('call_id')?.trim() ?? ''

  const [result, setResult] = useState<{
    callId: string
    call: CallMetadataViewModel | null
    error: string | null
  } | null>(null)

  const isLoading = Boolean(callId) && result?.callId !== callId
  const call = result?.callId === callId ? result.call : null
  const error = result?.callId === callId ? result.error : null

  useEffect(() => {
    if (!callId) {
      return
    }

    let cancelled = false

    callRestService
      .getCall(callId)
      .then((response) => {
        if (cancelled) return
        setResult({ callId, call: toCallMetadataViewModel(response), error: null })
      })
      .catch((err) => {
        if (cancelled) return
        setResult({
          callId,
          call: null,
          error: err instanceof ApiError ? err.message : 'Unable to load this call.',
        })
      })

    return () => {
      cancelled = true
    }
  }, [callId])

  return (
    <section className="page-shell">
      <div className="page-shell__header">
        <div>
          <p className="eyebrow">Records</p>
          <h2>Call history</h2>
        </div>
      </div>

      {!callId && (
        <div className="panel">
          <p className="panel__label">No call selected</p>
          <p>
            Add a call ID to the URL as <code>?call_id=&lt;call_id&gt;</code> to look up its
            details.
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
          <strong>Could not load call</strong>
          <span>{error}</span>
        </div>
      )}

      {callId && !isLoading && !error && call && (
        <div className="panel">
          <p className="panel__label">Call {call.callId}</p>
          <div className="info-list">
            <span>Status: {call.status}</span>
            <span>Start time: {formatUnixTimestamp(call.startTime)}</span>
            <span>End time: {call.endTime != null ? formatUnixTimestamp(call.endTime) : '—'}</span>
            <span>Utterance count: {call.utteranceCount}</span>
          </div>

          <div className="live-call__call-selector" style={{ marginTop: '1rem' }}>
            <Link to={`/live-call?call_id=${encodeURIComponent(call.callId)}`}>
              Open in Live Call
            </Link>
            <Link to={`/post-call-analysis?call_id=${encodeURIComponent(call.callId)}`}>
              Open Post-call Analysis
            </Link>
          </div>
        </div>
      )}
    </section>
  )
}