import type { ReactNode } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { RecordTime } from '../../../components/RecordTime'
import { Link } from 'react-router-dom'

import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import { adminRestService } from '../services/adminRestService'

import type { PostCallRepairStatusDto, RepairRunDto } from '../types/dto'

const REFRESH_INTERVAL_MS = 30000

function describeRun(run: RepairRunDto): ReactNode {
  const when = <RecordTime seconds={run.ran_at} />
  if (run.skipped_reason) {
    return <>Last sweep {when}: skipped — {run.skipped_reason}</>
  }
  return (
    <>
      Last sweep {when}: {run.pending} waiting, {run.repaired} repaired, {run.failed} failed,{' '}
      {run.gave_up} given up.
    </>
  )
}

// Completed calls whose post-call processing (summary, complaint close-out,
// customer message) never finished, with automatic and manual retries.
export function PostCallRepairPanel() {
  const [status, setStatus] = useState<PostCallRepairStatusDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyCallId, setBusyCallId] = useState<string | null>(null)
  const [isSweeping, setIsSweeping] = useState(false)
  const [notice, setNotice] = useState<ReactNode>(null)

  const load = useCallback(async () => {
    try {
      setStatus(await adminRestService.getPostCallStatus())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to load post-call processing.')
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const refresh = () => {
      if (!cancelled) {
        void load()
      }
    }
    refresh()
    const intervalId = window.setInterval(refresh, REFRESH_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [load])

  const retry = async (callId: string) => {
    setBusyCallId(callId)
    setNotice(null)
    try {
      const result = await adminRestService.retryPostCall(callId)
      setNotice(
        result.repaired
          ? `Call ${callId} is processed.`
          : `Call ${callId} still failed; check the server logs.`,
      )
      await load()
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : 'Retry failed.')
    } finally {
      setBusyCallId(null)
    }
  }

  const sweep = async () => {
    setIsSweeping(true)
    setNotice(null)
    try {
      const run = await adminRestService.runPostCallRepair()
      setNotice(describeRun(run))
      await load()
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : 'The sweep failed.')
    } finally {
      setIsSweeping(false)
    }
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h3 className="section-title">Post-call processing</h3>
          <p className="customer-panel__muted">
            Completed calls whose summary was never produced.{' '}
            {status &&
              (status.background_enabled
                ? 'They are retried automatically with increasing delays.'
                : 'Automatic retries are switched off.')}
          </p>
        </div>
        <button
          type="button"
          className="button button--secondary"
          disabled={isSweeping}
          onClick={() => void sweep()}
        >
          {isSweeping ? 'Sweeping…' : 'Run sweep now'}
        </button>
      </div>

      {status?.last_run && <p className="customer-panel__muted">{describeRun(status.last_run)}</p>}
      {notice && <p className="inline-notice">{notice}</p>}

      {error && (
        <StatePanel compact variant="error" title="Could not load post-call processing" description={error} />
      )}
      {!error && !status && <StatePanel compact variant="loading" title="Loading…" />}
      {status && status.pending.length === 0 && (
        <StatePanel compact title="All caught up" description="Every completed call has its post-call summary." />
      )}

      {status && status.pending.length > 0 && (
        <div className="card-stack">
          {status.pending.map((item) => (
            <article key={item.call_id} className="list-card">
              <div className="section-heading complaint-card__heading">
                <Link
                  className="text-link list-card__title"
                  to={`/post-call-analysis?call_id=${encodeURIComponent(item.call_id)}`}
                >
                  {item.call_id}
                </Link>
                <div className="list-card__meta">
                  <span className="badge">{item.attempts} attempts</span>
                  {item.gave_up && <span className="badge badge--danger">Retries stopped</span>}
                </div>
              </div>
              <div className="list-card__facts">
                <span>Waiting since: <RecordTime seconds={item.first_seen_at} /></span>
                {item.last_attempt_at !== null && (
                  <span>Last attempt: <RecordTime seconds={item.last_attempt_at} /></span>
                )}
              </div>
              {item.last_error && <p className="summary-delivery__message">{item.last_error}</p>}
              <div className="button-row">
                <button
                  type="button"
                  className="button"
                  disabled={busyCallId !== null}
                  onClick={() => void retry(item.call_id)}
                >
                  {busyCallId === item.call_id ? 'Retrying…' : 'Retry now'}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
