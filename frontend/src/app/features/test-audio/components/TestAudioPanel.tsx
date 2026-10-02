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
    // A row inside the Live Call box: caller number, upload, progress.
    // Styled as a temporary testing aid, not part of the regular workflow.
    <div className="test-audio" role="group" aria-label="Test audio (testing only)">
      <div className="test-audio__row">
        <span
          className="test-audio__tag"
          title="A temporary tool for testing: plays a recording as if it were a live phone call."
        >
          Testing only
        </span>
        <input
          className="test-audio__number"
          value={fromNumber}
          onChange={(event) => setFromNumber(event.target.value)}
          placeholder="Caller number (optional)"
          aria-label="Caller number (optional)"
          autoComplete="off"
          disabled={isBusy}
        />

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
            title="Plays a recording as a live phone call, in real time, through the telephony pipeline."
          >
            {replay.phase === 'preparing'
              ? 'Preparing…'
              : replay.phase === 'ending'
                ? 'Ending call…'
                : 'Upload test audio'}
          </button>
        )}

        {replay.fileName && replay.phase !== 'idle' && (
          <div className="test-audio__status">
            <strong title={replay.fileName}>{replay.fileName}</strong>
            <div
              className="test-audio__progress"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress)}
            >
              <span style={{ width: `${progress}%` }} />
            </div>
            <span className="test-audio__clock">
              {formatClock(replay.elapsedSeconds)} / {formatClock(replay.durationSeconds)}
            </span>
            {replay.phase === 'finished' && replay.callId && (
              <Link
                className="test-audio__link"
                to={`/post-call-analysis?call_id=${encodeURIComponent(replay.callId)}`}
              >
                Post Call analysis →
              </Link>
            )}
          </div>
        )}
      </div>

      {replay.error && (
        <p className="test-audio__error" role="alert">
          {replay.error}
        </p>
      )}
    </div>
  )
}
