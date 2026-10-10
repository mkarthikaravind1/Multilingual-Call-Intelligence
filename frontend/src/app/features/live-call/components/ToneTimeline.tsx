import { humanizeLabel } from '../../../format/text'
import { formatElapsedSeconds } from '../../../format/time'
import { LINE_TONES, lineToneKey } from '../../../format/tone'

import type { TranscriptTurnViewModel } from '../types/view-models'

type ToneTimelineProps = {
  transcript: TranscriptTurnViewModel[]
}

// How the customer's tone moved over the call: one bar per rated line, in
// order. Height and colour both follow the tone, so it reads without colour.
export function ToneTimeline({ transcript }: ToneTimelineProps) {
  const rated = transcript.filter((turn) => lineToneKey(turn.sentiment) !== null)
  if (rated.length === 0) {
    return null
  }

  return (
    <div className="tone-timeline">
      <div className="tone-timeline__heading">
        <span className="panel__label">Customer tone over the call</span>
        <ul className="tone-timeline__legend" aria-hidden="true">
          {LINE_TONES.map((tone) => (
            <li key={tone}>
              <span className={`tone-dot tone-dot--${tone}`} />
              {humanizeLabel(tone)}
            </li>
          ))}
        </ul>
      </div>
      <ol className="tone-timeline__bars">
        {rated.map((turn) => {
          const tone = lineToneKey(turn.sentiment)!
          const label = `${formatElapsedSeconds(turn.startTime)} · ${humanizeLabel(tone)}`
          return (
            <li
              key={turn.utteranceId}
              className={`tone-timeline__bar tone-timeline__bar--${tone}`}
              title={`${label}: ${turn.transcript}`}
            >
              <span className="visually-hidden">{label}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
