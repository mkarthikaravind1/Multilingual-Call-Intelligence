import { useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Link } from 'react-router-dom'

import type { TestAudioReplay } from '../hooks/useTestAudioReplay'

function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

type TestAudioPanelProps = {
  replay: TestAudioReplay
}

// Supervisor/admin tool: replay a recorded conversation as if it were a live
// phone call, to exercise every live and post-call feature end to end.
export function TestAudioPanel({ replay }: TestAudioPanelProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [fromNumber, setFromNumber] = useState('')

  const isBusy =
    replay.phase === 'preparing' || replay.phase === 'streaming' || replay.phase === 'ending'
  const progress =
    replay.durationSeconds > 0
      ? Math.min(100, (replay.elapsedSeconds / replay.durationSeconds) * 100)
      : 0

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) void replay.start(file, fromNumber)
  }

  return (
    <section className="test-audio panel" aria-label="Test audio">
      <div className="test-audio__row">
        <div className="test-audio__intro">
          <p className="panel__label">Test audio</p>
          <p className="test-audio__hint">
            Plays a recording as a live phone call, in real time, through the telephony pipeline.
          </p>
        </div>

        <label className="test-audio__field">
          <span>Caller number (optional)</span>
          <input
            value={fromNumber}
            onChange={(event) => setFromNumber(event.target.value)}
            placeholder="e.g. 9845000002"
            autoComplete="off"
            disabled={isBusy}
          />
        </label>

        <input
          ref={fileInputRef}
          type="file"
          accept="audio/*"
          hidden
          onChange={handleFile}
        />

        {replay.phase === 'streaming' ? (
          <button type="button" className="test-audio__button" onClick={replay.stop}>
            Stop and end call
          </button>
        ) : (
          <button
            type="button"
            className="test-audio__button"
            disabled={isBusy}
            onClick={() => fileInputRef.current?.click()}
          >
            {replay.phase === 'preparing'
              ? 'Preparing…'
              : replay.phase === 'ending'
                ? 'Ending call…'
                : 'Upload test audio'}
          </button>
        )}
      </div>

      {replay.fileName && replay.phase !== 'idle' && (
        <div className="test-audio__status">
          <div className="test-audio__status-line">
            <strong>{replay.fileName}</strong>
            <span>
              {formatClock(replay.elapsedSeconds)} / {formatClock(replay.durationSeconds)}
            </span>
          </div>
          <div
            className="test-audio__progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress)}
          >
            <span style={{ width: `${progress}%` }} />
          </div>
          {replay.phase === 'finished' && replay.callId && (
            <p className="test-audio__hint">
              Call ended. Post-call analysis runs in the background —{' '}
              <Link to={`/post-call-analysis?call_id=${encodeURIComponent(replay.callId)}`}>
                open post-call analysis
              </Link>{' '}
              in a minute.
            </p>
          )}
        </div>
      )}

      {replay.error && (
        <p className="test-audio__error" role="alert">
          {replay.error}
        </p>
      )}
    </section>
  )
}
