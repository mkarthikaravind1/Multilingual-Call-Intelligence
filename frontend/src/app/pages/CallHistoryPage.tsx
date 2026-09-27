import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { callRestService } from '../features/live-call/services/callRestService'
import { toCallMetadataViewModel } from '../features/live-call/adapters/toViewModel'
import type { CallMetadataViewModel } from '../features/live-call/types/view-models'
import { ApiError } from '../api/errors'
import { formatUnixTimestamp } from '../format/time'

const PAGE_SIZE = 20

type CallListState = {
  offset: number
  calls: CallMetadataViewModel[]
  total: number
  error: string | null
}

function CallList() {
  const [offset, setOffset] = useState(0)
  const [result, setResult] = useState<CallListState | null>(null)

  const isLoading = result?.offset !== offset
  const current = result?.offset === offset ? result : null

  useEffect(() => {
    let cancelled = false

    callRestService
      .listCalls(PAGE_SIZE, offset)
      .then((response) => {
        if (cancelled) return
        setResult({
          offset,
          calls: response.items.map(toCallMetadataViewModel),
          total: response.total,
          error: null,
        })
      })
      .catch((err) => {
        if (cancelled) return
        setResult({
          offset,
          calls: [],
          total: 0,
          error: err instanceof ApiError ? err.message : 'Unable to load call history.',
        })
      })

    return () => {
      cancelled = true
    }
  }, [offset])

  if (isLoading) {
    return (
      <div className="panel">
        <p>Loading call history…</p>
      </div>
    )
  }

  if (current?.error) {
    return (
      <div className="live-call__error" role="alert">
        <strong>Could not load call history</strong>
        <span>{current.error}</span>
      </div>
    )
  }

  if (!current || current.total === 0) {
    return (
      <div className="panel">
        <p className="panel__label">No calls yet</p>
        <p>Calls will appear here once they are started.</p>
      </div>
    )
  }

  const firstShown = offset + 1
  const lastShown = offset + current.calls.length

  return (
    <>
      <div className="panel panel--list">
        <div className="table-row table-row--head">
          <span>Call ID</span>
          <span>Status</span>
          <span>Utterances</span>
          <span>Open</span>
        </div>

        {current.calls.map((call) => (
          <div className="table-row" key={call.callId}>
            <span>{call.callId}</span>
            <span>{call.status}</span>
            <span>{call.utteranceCount}</span>
            <span className="call-history__actions">
              <Link
                className="call-history__link"
                to={`/live-call?call_id=${encodeURIComponent(call.callId)}`}
              >
                Live Call
              </Link>
              <Link
                className="call-history__link"
                to={`/post-call-analysis?call_id=${encodeURIComponent(call.callId)}`}
              >
                Post-call Analysis
              </Link>
            </span>
          </div>
        ))}
      </div>

      <div className="page-shell__header">
        <span>
          Showing {firstShown}–{lastShown} of {current.total}
        </span>
        <div>
          <button
            type="button"
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
          >
            Previous
          </button>{' '}
          <button
            type="button"
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={lastShown >= current.total}
          >
            Next
          </button>
        </div>
      </div>
    </>
  )
}

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

      {!callId && <CallList />}

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