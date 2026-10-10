import { humanizeLabel } from '../../../format/text'
import { formatElapsedSeconds } from '../../../format/time'
import { lineToneKey } from '../../../format/tone'
import { ToneTimeline } from './ToneTimeline'

import type {
  TranscriptTurnViewModel,
} from '../types/view-models'

type TranscriptPanelProps = {
  transcript: TranscriptTurnViewModel[]
}

function roleLabel(role: string) {
  const normalized =
    role.toUpperCase()

  if (normalized.includes('ICR')) {
    return 'ICR'
  }

  if (
    normalized.includes(
      'CUSTOMER',
    )
  ) {
    return 'Customer'
  }

  return role || 'Unknown speaker'
}

export function TranscriptPanel({
  transcript,
}: TranscriptPanelProps) {
  return (
    <section className="panel live-call__transcript-panel">
      <div className="live-call__section-heading">
        <div>
          <p className="panel__label">
            Live transcript
          </p>

          <h4>Conversation</h4>
        </div>

        <span className="live-call__count-badge">
          {transcript.length} turns
        </span>
      </div>

      {transcript.length === 0 ? (
        <div className="live-call__empty-state">
          <strong>
            No transcript turns yet
          </strong>

          <span>
            Finalized utterances received
            by the backend will appear
            here.
          </span>
        </div>
      ) : (
        <>
        <ToneTimeline transcript={transcript} />
        <div className="live-call__transcript-list">
          {transcript.map((turn) => {
            const tone = lineToneKey(turn.sentiment)
            return (
            <article
              className={`live-call__turn live-call__turn--${roleLabel(
                turn.speakerRole,
              ).toLowerCase()}${tone ? ` live-call__turn--tone-${tone}` : ''}`}
              key={turn.utteranceId}
            >
              <div className="live-call__turn-meta">
                <span className="live-call__speaker">
                  {roleLabel(
                    turn.speakerRole,
                  )}
                </span>

                {turn.languages.length >
                  0 && (
                  <span className="live-call__language">
                    {turn.languages.join(
                      ' · ',
                    )}
                  </span>
                )}

                <span className="live-call__timestamp">
                  {formatElapsedSeconds(
                    turn.startTime,
                  )}
                </span>

                {tone && (
                  <span className="live-call__turn-tone">
                    <span className={`tone-dot tone-dot--${tone}`} aria-hidden="true" />
                    {humanizeLabel(tone)}
                  </span>
                )}
              </div>

              <p>
                {turn.transcript}
              </p>

              {turn.complaintCategories.length > 0 && (
                <div className="live-call__turn-categories">
                  {turn.complaintCategories.map((category) => (
                    <span className="live-call__turn-category" key={category}>
                      {category}
                    </span>
                  ))}
                  {turn.multiCategory && (
                    <span
                      className="live-call__turn-multi"
                      title="This line covers more than one complaint"
                    >
                      Several issues
                    </span>
                  )}
                </div>
              )}
            </article>
            )
          })}
        </div>
        </>
      )}
    </section>
  )
}