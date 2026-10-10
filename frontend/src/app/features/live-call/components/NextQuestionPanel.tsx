import { useEffect, useState } from 'react'

import { callRestService } from '../services/callRestService'
import type { QuestionOutcomeChoice } from '../types/dto'
import type {
  QuestionSuggestionViewModel,
} from '../types/view-models'

type NextQuestionPanelProps = {
  // The suggested questions, the most relevant first.
  suggestions: QuestionSuggestionViewModel[]
  emptyMessage?: string
  // With the call's id, the executive can accept or skip each question
  // while the call is live.
  callId?: string
  isCallActive?: boolean
}

export function NextQuestionPanel({
  suggestions,
  emptyMessage = 'No next-question suggestion has been returned yet.',
  callId,
  isCallActive = false,
}: NextQuestionPanelProps) {
  // What was chosen for each question of this call, by its text.
  const [outcomes, setOutcomes] = useState<Record<string, QuestionOutcomeChoice>>({})
  // The question whose choice is being saved.
  const [saving, setSaving] = useState<string | null>(null)
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

  const choose = async (
    suggestion: QuestionSuggestionViewModel,
    outcome: QuestionOutcomeChoice,
  ) => {
    if (!callId) return
    setSaving(suggestion.question)
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
      setSaving(null)
    }
  }

  return (
    <section className="panel panel--highlight next-question-panel">
      <p className="panel__label">
        Next-question engine
      </p>

      <h4 className="live-call__metric-title">
        {suggestions.length > 1 ? 'Suggested questions' : 'Suggested question'}
      </h4>

      {suggestions.length > 0 ? (
        <>
          {suggestions.length > 1 && (
            <p className="customer-panel__muted">Most relevant first.</p>
          )}
          <ol className="question-list">
            {suggestions.map((suggestion, index) => {
              const chosen = outcomes[suggestion.question] ?? null
              return (
                <li
                  className={`question-list__item${chosen ? ' question-list__item--handled' : ''}`}
                  key={suggestion.question}
                >
                  <span className="question-list__rank" aria-hidden="true">
                    {index + 1}
                  </span>
                  <div className="question-list__body">
                    <div className="live-call__question">
                      <p className="live-call__question-text" lang={suggestion.language}>
                        “{suggestion.question}”
                      </p>

                      {suggestion.questionEnglish && (
                        <p className="live-call__question-english" lang="en">
                          {suggestion.questionEnglish}
                        </p>
                      )}
                    </div>

                    <p className="question-list__about">
                      <span className="live-call__turn-category">
                        {suggestion.targetCategory}
                      </span>
                      <span className="live-call__evidence">{suggestion.reason}</span>
                    </p>

                    {callId && isCallActive && (
                      <div className="question-outcome">
                        <button
                          type="button"
                          className={`button${chosen === 'accepted' ? '' : ' button--secondary'}`}
                          aria-pressed={chosen === 'accepted'}
                          disabled={saving === suggestion.question}
                          onClick={() => void choose(suggestion, 'accepted')}
                        >
                          {chosen === 'accepted' ? 'Accepted' : 'Accept'}
                        </button>
                        <button
                          type="button"
                          className={`button${chosen === 'skipped' ? '' : ' button--secondary'}`}
                          aria-pressed={chosen === 'skipped'}
                          disabled={saving === suggestion.question}
                          onClick={() => void choose(suggestion, 'skipped')}
                        >
                          {chosen === 'skipped' ? 'Skipped' : 'Skip'}
                        </button>
                        {chosen && (
                          <span className="customer-panel__muted">You can change this.</span>
                        )}
                      </div>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>
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
