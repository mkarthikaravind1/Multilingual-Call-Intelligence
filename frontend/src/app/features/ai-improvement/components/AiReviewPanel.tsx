import { useEffect, useState } from 'react'

import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import { humanizeLabel } from '../../../format/text'
import { learningRestService } from '../services/learningRestService'

import type {
  CallObservationDto,
  LearningComponent,
  LearningFeedbackDto,
  LearningFeedbackRequestDto,
  QuestionOutcome,
} from '../types/dto'

const COMPONENT_LABELS: Partial<Record<LearningComponent, string>> = {
  complaint_detection: 'Complaint detected',
  sentiment_analysis: 'Customer tone',
  next_question: 'Suggested question',
}

const COMPONENT_ORDER: LearningComponent[] = [
  'complaint_detection',
  'sentiment_analysis',
  'next_question',
]

type AiReviewPanelProps = {
  callId: string
}

function displayValue(observation: CallObservationDto, value: string): string {
  // Tone labels arrive as enum values (e.g. NEGATIVE); categories and
  // questions are already readable text.
  return observation.component === 'sentiment_analysis' ? humanizeLabel(value) : value
}

function describeFeedback(
  observation: CallObservationDto,
  feedback: LearningFeedbackDto,
): string {
  if (feedback.outcome === 'helpful') {
    return 'Marked as helpful'
  }
  if (feedback.outcome === 'not_helpful') {
    return 'Marked as not helpful'
  }
  if (feedback.corrected_value) {
    return `Corrected to “${displayValue(observation, feedback.corrected_value)}”`
  }
  return 'Reviewed'
}

export function AiReviewPanel({ callId }: AiReviewPanelProps) {
  const [observations, setObservations] = useState<CallObservationDto[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const [submittingId, setSubmittingId] = useState<string | null>(null)
  const [editingQuestionId, setEditingQuestionId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setIsLoading(true)
      setLoadError(null)

      try {
        const data = await learningRestService.listCallObservations(callId)
        if (!cancelled) {
          setObservations(data)
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(
            err instanceof ApiError ? err.message : 'Unable to load the AI output for this call.',
          )
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [callId])

  const submit = async (
    observation: CallObservationDto,
    request: Omit<LearningFeedbackRequestDto, 'observation_id'>,
  ) => {
    const observationId = observation.observation_id
    setSubmittingId(observationId)
    setRowErrors((current) => ({ ...current, [observationId]: '' }))

    try {
      const feedback = await learningRestService.submitFeedback(callId, {
        observation_id: observationId,
        ...request,
      })
      setObservations((current) =>
        current.map((item) =>
          item.observation_id === observationId ? { ...item, feedback } : item,
        ),
      )
      setEditingQuestionId(null)
    } catch (err) {
      setRowErrors((current) => ({
        ...current,
        [observationId]:
          err instanceof ApiError ? err.message : 'Unable to save your feedback.',
      }))
    } finally {
      setSubmittingId(null)
    }
  }

  const correct = (observation: CallObservationDto) => {
    const value = drafts[observation.observation_id]?.trim()
    if (value) {
      void submit(observation, { feedback_type: 'human_correction', corrected_value: value })
    }
  }

  const rateQuestion = (observation: CallObservationDto, outcome: QuestionOutcome) => {
    void submit(observation, { feedback_type: 'question_effectiveness', outcome })
  }

  const setDraft = (observationId: string, value: string) => {
    setDrafts((current) => ({ ...current, [observationId]: value }))
  }

  const sorted = [...observations].sort(
    (a, b) =>
      COMPONENT_ORDER.indexOf(a.component) - COMPONENT_ORDER.indexOf(b.component) ||
      a.created_at - b.created_at,
  )

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="panel__label">Review AI output</p>
          <h3 className="section-title">Did the AI get this call right?</h3>
        </div>
      </div>

      <p className="inline-notice">
        Correct anything the AI got wrong on this call. When the same correction
        comes up on several calls, it becomes an improvement suggestion for a
        supervisor to review in the AI Improvement Center.
      </p>

      <div className="card-stack spaced-top">
        {isLoading && <StatePanel compact variant="loading" title="Loading AI output…" />}

        {!isLoading && loadError && (
          <StatePanel compact variant="error" title="Could not load AI output" description={loadError} />
        )}

        {!isLoading && !loadError && sorted.length === 0 && (
          <StatePanel
            compact
            title="Nothing to review"
            description="The AI has not produced any complaint, tone or question output for this call."
          />
        )}

        {!isLoading &&
          !loadError &&
          sorted.map((observation) => {
            const id = observation.observation_id
            const isSubmitting = submittingId === id
            const isBusy = submittingId !== null
            const rowError = rowErrors[id]
            const draft = drafts[id] ?? ''
            const choices = observation.correction_options.filter(
              (option) => option !== observation.predicted_value,
            )
            const isQuestion = observation.component === 'next_question'

            return (
              <article key={id} className="list-card">
                <div className="list-card__meta">
                  <span className="badge">
                    {COMPONENT_LABELS[observation.component] ?? humanizeLabel(observation.component)}
                  </span>
                  {observation.feedback && (
                    <span className="badge badge--success">Reviewed</span>
                  )}
                </div>

                <strong className="list-card__title">
                  {displayValue(observation, observation.predicted_value)}
                </strong>

                {observation.feedback ? (
                  <p>
                    {describeFeedback(observation, observation.feedback)} by{' '}
                    {observation.feedback.source === 'icr' ? 'the ICR' : 'a supervisor'}.
                  </p>
                ) : (
                  <>
                    {choices.length > 0 && (
                      <div className="review-form">
                        <label htmlFor={`correction-${id}`}>Should have been</label>
                        <select
                          id={`correction-${id}`}
                          value={draft}
                          disabled={isBusy}
                          onChange={(event) => setDraft(id, event.target.value)}
                        >
                          <option value="">Choose the correct value…</option>
                          {choices.map((option) => (
                            <option key={option} value={option}>
                              {displayValue(observation, option)}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          className="button button--secondary"
                          disabled={isBusy || !draft}
                          onClick={() => correct(observation)}
                        >
                          {isSubmitting ? 'Saving…' : 'Submit correction'}
                        </button>
                      </div>
                    )}

                    {isQuestion && (
                      <div className="button-row">
                        <button
                          type="button"
                          className="button button--secondary"
                          disabled={isBusy}
                          onClick={() => rateQuestion(observation, 'helpful')}
                        >
                          Helpful
                        </button>
                        <button
                          type="button"
                          className="button button--secondary"
                          disabled={isBusy}
                          onClick={() => rateQuestion(observation, 'not_helpful')}
                        >
                          Not helpful
                        </button>
                        <button
                          type="button"
                          className="button button--secondary"
                          disabled={isBusy}
                          onClick={() =>
                            setEditingQuestionId((current) => (current === id ? null : id))
                          }
                        >
                          Suggest a better question
                        </button>
                      </div>
                    )}

                    {isQuestion && editingQuestionId === id && (
                      <div className="review-form">
                        <label htmlFor={`question-${id}`}>Better question</label>
                        <input
                          id={`question-${id}`}
                          value={draft}
                          maxLength={500}
                          disabled={isBusy}
                          placeholder="What should the ICR have asked?"
                          onChange={(event) => setDraft(id, event.target.value)}
                        />
                        <button
                          type="button"
                          className="button"
                          disabled={isBusy || !draft.trim()}
                          onClick={() => correct(observation)}
                        >
                          {isSubmitting ? 'Saving…' : 'Submit'}
                        </button>
                      </div>
                    )}
                  </>
                )}

                {rowError && (
                  <p className="review-form__error" role="alert">
                    {rowError}
                  </p>
                )}
              </article>
            )
          })}
      </div>
    </section>
  )
}
