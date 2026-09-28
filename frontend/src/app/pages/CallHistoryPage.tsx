import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { callRestService } from '../features/live-call/services/callRestService'
import { toCallMetadataViewModel } from '../features/live-call/adapters/toViewModel'
import { CallTable } from '../features/live-call/components/CallTable'
import type { CallMetadataViewModel } from '../features/live-call/types/view-models'
import { ApiError } from '../api/errors'
import { CallStatusBadge } from '../components/CallStatusBadge'
import { StatePanel } from '../components/StatePanel'
import { formatCallDuration } from '../format/time'

const PAGE_SIZE = 20

type CallListState = {
  requestKey: string
  calls: CallMetadataViewModel[]
  total: number
  error: string | null
}

function CallList() {
  const [offset, setOffset] = useState(0)
  const [reloadCount, setReloadCount] = useState(0)
  const [result, setResult] = useState<CallListState | null>(null)

  const requestKey = `${offset}:${reloadCount}`
  const isLoading = result?.requestKey !== requestKey
  const current = result?.requestKey === requestKey ? result : null

  useEffect(() => {
    let cancelled = false

    callRestService
      .listCalls(PAGE_SIZE, offset)
      .then((response) => {
        if (cancelled) return
        setResult({
          requestKey,
          calls: response.items.map(toCallMetadataViewModel),
          total: response.total,
          error: null,
        })
      })
      .catch((err) => {
        if (cancelled) return
        setResult({
          requestKey,
          calls: [],
          total: 0,
          error: err instanceof ApiError ? err.message : 'Unable to load call history.',
        })
      })

    return () => {
      cancelled = true
    }
  }, [offset, requestKey])

  const refreshButton = (
    <button
      type="button"
      className="button button--secondary"
      onClick={() => setReloadCount((count) => count + 1)}
      disabled={isLoading}
    >
      Refresh
    </button>
  )

  if (isLoading) {
    return <StatePanel variant="loading" title="Loading call history…" />
  }

  if (current?.error) {
    return (
      <StatePanel
        variant="error"
        title="Could not load call history"
        description={current.error}
        action={refreshButton}
      />
    )
  }

  if (!current || current.total === 0) {
    return (
      <StatePanel
        title="No calls yet"
        description="Calls appear here once they are started from Live Call or received through telephony."
        action={
          <Link className="button" to="/live-call">
            Go to Live Call
          </Link>
        }
      />
    )
  }

  const firstShown = offset + 1
  const lastShown = offset + current.calls.length
  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil(current.total / PAGE_SIZE))

  return (
    <>
      <CallTable calls={current.calls} />

      <div className="pager">
        <span>
          Showing <strong>{firstShown}–{lastShown}</strong> of{' '}
          <strong>{current.total}</strong> calls · Page {page} of {pageCount}
        </span>
        <div className="button-row">
          {refreshButton}
          <button
            type="button"
            className="button button--secondary"
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
          >
            Previous
          </button>
          <button
            type="button"
            className="button button--secondary"
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

  const backToList = (
    <Link className="button button--secondary" to="/call-history">
      Back to all calls
    </Link>
  )

  return (
    <section className="page-shell">
      {callId && (
        <div className="page-shell__header page-shell__header--actions">{backToList}</div>
      )}

      {!callId && <CallList />}

      {callId && isLoading && (
        <StatePanel variant="loading" title={`Loading call ${callId}…`} />
      )}

      {callId && !isLoading && error && (
        <StatePanel
          variant="error"
          title="Could not load call"
          description={error}
          action={backToList}
        />
      )}

      {callId && !isLoading && !error && call && (
        <div className="panel">
          <div className="section-heading">
            <div>
              <p className="panel__label">Call</p>
              <h3 className="section-title">{call.callId}</h3>
            </div>
            <CallStatusBadge status={call.status} />
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

          <div className="button-row spaced-top">
            <Link
              className="button"
              to={`/live-call?call_id=${encodeURIComponent(call.callId)}`}
            >
              Open in Live Call
            </Link>
            <Link
              className="button button--secondary"
              to={`/post-call-analysis?call_id=${encodeURIComponent(call.callId)}`}
            >
              Open Post-call Analysis
            </Link>
          </div>
        </div>
      )}
    </section>
  )
}
