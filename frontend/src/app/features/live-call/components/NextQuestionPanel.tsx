import { useEffect, useState } from 'react'

import { callRestService } from '../services/callRestService'
import type { QuestionOutcomeChoice } from '../types/dto'
import type {
  QuestionSuggestionViewModel,
} from '../types/view-models'

type NextQuestionPanelProps = {
  suggestion:
    | QuestionSuggestionViewModel
    | null
  emptyMessage?: string
  // With the call's id, the executive can accept or skip the question
  // while the call is live.
  callId?: string
  isCallActive?: boolean
}

export function NextQuestionPanel({
  suggestion,
  emptyMessage = 'No next-question suggestion has been returned yet.',
  callId,
  isCallActive = false,
}: NextQuestionPanelProps) {
  // What was chosen for each question of this call, by its text.
  const [outcomes, setOutcomes] = useState<Record<string, QuestionOutcomeChoice>>({})
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (!callId) return
    let cancelled = false
    callRestService
      .listQuestionOutcomes(callId)
      .then((list) => {
        if (cancelled) return
        setOutcomes(Object.fromEntries(list.map((item) => [item.question, item.outcome])))
      })
      .catch(() => {
        // The buttons still work; earlier choices are just not shown.
      })
    return () => {
      cancelled = true
    }
  }, [callId])

  const chosen = suggestion ? (outcomes[suggestion.question] ?? null) : null

  const choose = async (outcome: QuestionOutcomeChoice) => {
    if (!callId || !suggestion) return
    setIsSaving(true)
    setSaveError(null)
    try {
      await callRestService.recordQuestionOutcome(
        callId,
        suggestion.question,
        suggestion.targetCategory,
        outcome,
      )
      setOutcomes((current) => ({ ...current, [suggestion.question]: outcome }))
    } catch {
      setSaveError('Could not save your choice. Try again.')
    } finally {
      setIsSaving(false)
    }
  }

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

          {callId && isCallActive && (
            <div className="question-outcome">
              <button
                type="button"
                className={`button${chosen === 'accepted' ? '' : ' button--secondary'}`}
                aria-pressed={chosen === 'accepted'}
                disabled={isSaving}
                onClick={() => void choose('accepted')}
              >
                {chosen === 'accepted' ? 'Accepted' : 'Accept'}
              </button>
              <button
                type="button"
                className={`button${chosen === 'skipped' ? '' : ' button--secondary'}`}
                aria-pressed={chosen === 'skipped'}
                disabled={isSaving}
                onClick={() => void choose('skipped')}
              >
                {chosen === 'skipped' ? 'Skipped' : 'Skip'}
              </button>
              <span className="customer-panel__muted">
                {chosen ? 'You can change this.' : 'Will you ask this question?'}
              </span>
            </div>
          )}
          {saveError && (
            <p className="review-form__error" role="alert">
              {saveError}
            </p>
          )}
        </>
      ) : (
        <p className="live-call__compact-empty">
          {emptyMessage}
        </p>
      )}
    </section>
  )
}