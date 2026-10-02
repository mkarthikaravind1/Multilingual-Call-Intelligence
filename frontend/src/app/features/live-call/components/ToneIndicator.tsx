import { humanizeLabel } from '../../../format/text'
import { sentimentTone } from '../../../format/tone'

import type {
  SentimentViewModel,
} from '../types/view-models'

type ToneIndicatorProps = {
  sentiment: SentimentViewModel | null
  // Names the panel in its heading (for pages that hide the small labels).
  compact?: boolean
}

export function ToneIndicator({
  sentiment,
  compact = false,
}: ToneIndicatorProps) {
  const tone = sentiment ? sentimentTone(sentiment.label) : 'neutral'

  return (
    <section className={`panel tone--${tone}`}>
      <p className="panel__label">
        Customer tone
      </p>

      <h4 className="live-call__metric-title">
        {compact && 'Customer tone: '}
        {sentiment
          ? humanizeLabel(sentiment.label)
          : 'Not available yet'}
      </h4>

      {sentiment ? (
        <>
          <div className="live-call__confidence-row">
            <span>
              Confidence
            </span>

            <strong>
              {Math.round(
                sentiment.confidence *
                  100,
              )}
              %
            </strong>
          </div>

          <div
            className="live-call__confidence-track"
            aria-hidden="true"
          >
            <span
              style={{
                width: `${Math.min(
                  Math.max(
                    sentiment.confidence *
                      100,
                    0,
                  ),
                  100,
                )}%`,
              }}
            />
          </div>

          <p className="live-call__evidence">
            {sentiment.evidence ||
              'No evidence returned.'}
          </p>
        </>
      ) : (
        <p className="live-call__compact-empty">
          Sentiment appears once the customer has spoken.
        </p>
      )}
    </section>
  )
}