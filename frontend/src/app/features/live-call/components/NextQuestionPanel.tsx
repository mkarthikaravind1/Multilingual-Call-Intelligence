import type {
  QuestionSuggestionViewModel,
} from '../types/view-models'

type NextQuestionPanelProps = {
  suggestion:
    | QuestionSuggestionViewModel
    | null
  emptyMessage?: string
}

export function NextQuestionPanel({
  suggestion,
  emptyMessage = 'No next-question suggestion has been returned yet.',
}: NextQuestionPanelProps) {
  return (
    <section className="panel panel--highlight next-question-panel">
      <p className="panel__label">
        Next-question engine
      </p>

      <h4 className="live-call__metric-title">
        Suggested question
      </h4>

      {suggestion ? (
        <>
          <div className="live-call__question">
            <p
              className="live-call__question-text"
              lang={suggestion.language}
            >
              “{suggestion.question}”
            </p>

            {suggestion.questionEnglish && (
              <p
                className="live-call__question-english"
                lang="en"
              >
                {suggestion.questionEnglish}
              </p>
            )}
          </div>

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
          {emptyMessage}
        </p>
      )}
    </section>
  )
}