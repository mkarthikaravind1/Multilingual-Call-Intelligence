import type {
  SentimentViewModel,
} from '../types/view-models'

type ToneIndicatorProps = {
  sentiment: SentimentViewModel | null
}

export function ToneIndicator({
  sentiment,
}: ToneIndicatorProps) {
  return (
    <section className="panel">
      <p className="panel__label">
        Customer tone
      </p>

      <h4 className="live-call__metric-title">
        {sentiment?.label ??
          'Not available yet'}
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
          Waiting for backend sentiment
          analysis.
        </p>
      )}
    </section>
  )
}