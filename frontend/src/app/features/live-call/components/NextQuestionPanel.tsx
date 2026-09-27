import type {
  QuestionSuggestionViewModel,
} from '../types/view-models'

type NextQuestionPanelProps = {
  suggestion:
    | QuestionSuggestionViewModel
    | null
}

export function NextQuestionPanel({
  suggestion,
}: NextQuestionPanelProps) {
  return (
    <section className="panel panel--highlight">
      <p className="panel__label">
        Next-question engine
      </p>

      <h4 className="live-call__metric-title">
        Suggested question
      </h4>

      {suggestion ? (
        <>
          <p className="live-call__question">
            “{suggestion.question}”
          </p>

          <div className="live-call__detail-grid">
            <span>
              Target
            </span>

            <strong>
              {suggestion.targetCategory}
            </strong>

            <span>
              Priority
            </span>

            <strong>
              {suggestion.priority}
            </strong>

            <span>
              Confidence
            </span>

            <strong>
              {suggestion.confidence == null
                ? '—'
                : `${Math.round(
                    suggestion.confidence * 100,
                  )}%`}
            </strong>
          </div>

          <p className="live-call__evidence">
            {suggestion.reason}
          </p>
        </>
      ) : (
        <p className="live-call__compact-empty">
          No next-question suggestion has
          been returned yet.
        </p>
      )}
    </section>
  )
}