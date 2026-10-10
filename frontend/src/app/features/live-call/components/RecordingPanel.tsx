import { useEffect, useState } from 'react'

import { ApiError } from '../../../api/errors'
import { formatElapsedSeconds, formatRecordTimestamp } from '../../../format/time'
import { callRestService } from '../services/callRestService'
import type { CallRecordingDto } from '../types/dto'

type RecordingPanelProps = {
  callId: string
}

// A finished call's recording, for supervisors and admins. The audio is
// fetched only when asked for (each fetch is logged as a listen) and is
// never started by the page itself.
export function RecordingPanel({ callId }: RecordingPanelProps) {
  const [info, setInfo] = useState<CallRecordingDto | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    callRestService
      .getRecording(callId)
      .then((loaded) => {
        if (!cancelled) setInfo(loaded)
      })
      .catch(() => {
        // Without the details the panel stays hidden.
      })
    return () => {
      cancelled = true
    }
  }, [callId])

  // The decrypted audio lives only in this page: let go of it on leaving.
  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl)
    }
  }, [audioUrl])

  // Nothing to show when this server keeps no recordings.
  if (!info || !info.enabled) {
    return null
  }

  const load = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const blob = await callRestService.getRecordingAudio(callId)
      setAudioUrl(URL.createObjectURL(blob))
      setInfo((current) => (current ? { ...current, plays: current.plays + 1 } : current))
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 404
          ? 'The recording is no longer available.'
          : 'Could not load the recording.',
      )
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <section className="panel recording-panel">
      <h4 className="live-call__panel-title">Call recording</h4>

      {info.deleted_at != null && (
        <p className="customer-panel__muted">
          Removed on {formatRecordTimestamp(info.deleted_at)}, at the end of its retention period.
        </p>
      )}

      {info.deleted_at == null && !info.available && (
        <p className="customer-panel__muted">
          This call has no recording. Calls started in the web app are not recorded.
        </p>
      )}

      {info.available && (
        <>
          <p className="customer-panel__muted">
            {formatElapsedSeconds(info.duration_seconds ?? 0)}
            {info.channels === 2 ? ' · caller on the left, executive on the right' : ''}
            {info.delete_after != null &&
              ` · kept until ${formatRecordTimestamp(info.delete_after)}`}
            {` · listened to ${info.plays} ${info.plays === 1 ? 'time' : 'times'}`}
          </p>

          {audioUrl ? (
            <audio className="recording-panel__player" controls preload="metadata" src={audioUrl} />
          ) : (
            <button
              type="button"
              className="button button--secondary"
              disabled={isLoading}
              onClick={() => void load()}
            >
              {isLoading ? 'Loading…' : 'Load recording'}
            </button>
          )}
          <p className="customer-panel__muted">Each time it is loaded is logged with your name.</p>
        </>
      )}

      {error && (
        <p className="review-form__error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
