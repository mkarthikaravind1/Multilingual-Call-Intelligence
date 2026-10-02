import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { RecordTime } from '../components/RecordTime'
import { useAuth } from '../auth/useAuth'
import { ApiError } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { humanizeLabel } from '../format/text'

import { learningRestService } from '../features/ai-improvement/services/learningRestService'
import { EmergingComplaintsPanel } from '../features/complaints/components/EmergingComplaintsPanel'

import { LEARNING_COMPONENTS } from '../features/ai-improvement/types/dto'
import type {
  ActiveImprovementDto,
  LearningCandidateDto,
  LearningComponent,
  LearningEvidenceDto,
  LearningPatternDto,
} from '../features/ai-improvement/types/dto'

// "Customer Name(Vehicle Number)", or as much of it as is known.
function evidenceCaller(item: LearningEvidenceDto): string {
  if (!item.customer_name) return 'Unknown caller'
  return item.vehicle_registration
    ? `${item.customer_name}(${item.vehicle_registration})`
    : item.customer_name
}

type ReviewNotice = {
  candidateTitle: string
  action: 'approve' | 'reject'
}

export function AiImprovementCenterPage() {
  const { session } = useAuth()
  const canReviewCandidates = session?.role === 'SUPERVISOR' || session?.role === 'ADMIN'
  const [candidates, setCandidates] = useState<LearningCandidateDto[]>([])
  const [patterns, setPatterns] = useState<LearningPatternDto[]>([])
  const [evidence, setEvidence] = useState<LearningEvidenceDto[]>([])
  const [improvements, setImprovements] = useState<ActiveImprovementDto[]>([])
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null)
  const [improvementError, setImprovementError] = useState<string | null>(null)

  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [reviewNotice, setReviewNotice] = useState<ReviewNotice | null>(null)
  const [reviewingCandidateId, setReviewingCandidateId] =
    useState<string | null>(null)
  // Components the evidence list is limited to; empty shows every component.
  const [evidenceComponents, setEvidenceComponents] = useState<LearningComponent[]>([])

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const [candidateData, patternData, evidenceData, improvementData] =
          await Promise.all([
            learningRestService.listCandidates(),
            learningRestService.listPatterns(),
            learningRestService.listEvidence(),
            learningRestService.listImprovements(),
          ])

        if (cancelled) {
          return
        }

        setCandidates(candidateData)
        setPatterns(patternData)
        setEvidence(evidenceData)
        setImprovements(improvementData)
      } catch (err) {
        if (cancelled) {
          return
        }

        setError(
          err instanceof Error
            ? err.message
            : 'Unable to load AI improvement data.',
        )
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
  }, [])

  const handleReview = async (
    candidate: LearningCandidateDto,
    action: 'approve' | 'reject',
  ) => {
    setReviewingCandidateId(candidate.candidate_id)
    setReviewError(null)
    setReviewNotice(null)

    try {
      const updatedCandidate =
        action === 'approve'
          ? await learningRestService.approveCandidate(candidate.candidate_id)
          : await learningRestService.rejectCandidate(candidate.candidate_id)

      setCandidates((currentCandidates) =>
        currentCandidates.map((current) =>
          current.candidate_id === candidate.candidate_id
            ? updatedCandidate
            : current,
        ),
      )
      setReviewNotice({ candidateTitle: candidate.title, action })

      if (action === 'approve') {
        // Approval activates the improvement; show it in the active list.
        try {
          setImprovements(await learningRestService.listImprovements())
        } catch {
          // The approval itself succeeded; the list refreshes on next load.
        }
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setReviewError(err.message)
      } else {
        setReviewError(
          `Unable to ${action} the improvement candidate.`,
        )
      }
    } finally {
      setReviewingCandidateId(null)
    }
  }

  const handleDeactivate = async (improvement: ActiveImprovementDto) => {
    setDeactivatingId(improvement.improvement_id)
    setImprovementError(null)

    try {
      const updated = await learningRestService.deactivateImprovement(
        improvement.improvement_id,
      )
      setImprovements((current) =>
        current.map((item) =>
          item.improvement_id === updated.improvement_id ? updated : item,
        ),
      )
    } catch (err) {
      setImprovementError(
        err instanceof ApiError ? err.message : 'Unable to deactivate the improvement.',
      )
    } finally {
      setDeactivatingId(null)
    }
  }

  const pendingCandidates = candidates.filter(
    (candidate) => candidate.status === 'pending_review',
  )

  const activeImprovements = improvements.filter(
    (improvement) => improvement.status === 'active',
  )

  const visibleEvidence = evidence
    .filter(
      (item) => evidenceComponents.length === 0 || evidenceComponents.includes(item.component),
    )
    .sort((a, b) => b.created_at - a.created_at)
  // Only components that have evidence are offered as filters.
  const presentComponents = LEARNING_COMPONENTS.filter((component) =>
    evidence.some((item) => item.component === component),
  )

  const metrics = [
    { label: 'Suggested improvements', value: pendingCandidates.length, caption: 'Pending human review' },
    { label: 'Active improvements', value: activeImprovements.length, caption: 'Guiding the live AI' },
    { label: 'Learning patterns', value: patterns.length, caption: 'Patterns discovered from call evidence' },
    { label: 'Learning evidence', value: evidence.length, caption: 'Evidence records collected from calls' },
  ]

  return (
    <section className="page-shell">
      {isLoading && (
        <StatePanel variant="loading" title="Loading AI improvement data…" />
      )}

      {!isLoading && error && (
        <StatePanel
          variant="error"
          title="Could not load the learning center"
          description={error}
        />
      )}

      {!isLoading && !error && (
        <>
          <div className="kpi-grid">
            {metrics.map((metric) => (
              <article key={metric.label} className="panel">
                <p className="panel__label">{metric.label}</p>
                <h3>{metric.value}</h3>
                <span>{metric.caption}</span>
              </article>
            ))}
          </div>

          <div className="page-shell__grid page-shell__grid--wide">
            <section className="panel">
              <div className="section-heading">
                <h3 className="section-title">Improvement candidates</h3>
                {!canReviewCandidates && (
                  <span className="badge">Review requires Supervisor or Admin</span>
                )}
              </div>

              <p className="inline-notice">
                Candidates come from corrections made on the Post-call Analysis
                page. Approving one activates it: its guidance is given to the
                live AI on every following call until it is deactivated.
              </p>

              {reviewNotice && (
                <p className="inline-notice inline-notice--success spaced-top" role="status">
                  {reviewNotice.action === 'approve'
                    ? `“${reviewNotice.candidateTitle}” was approved and is now active.`
                    : `“${reviewNotice.candidateTitle}” was rejected.`}
                </p>
              )}

              {reviewError && (
                <div className="spaced-top">
                  <StatePanel
                    variant="error"
                    compact
                    title="Review failed"
                    description={reviewError}
                  />
                </div>
              )}

              <div className="card-stack spaced-top">
                {candidates.length === 0 ? (
                  <StatePanel
                    compact
                    title="No improvement candidates yet"
                    description="A candidate is proposed when the same correction is made on at least two calls."
                  />
                ) : (
                  candidates.map((candidate) => {
                    const isReviewing =
                      reviewingCandidateId === candidate.candidate_id

                    return (
                      <article key={candidate.candidate_id} className="list-card">
                        <div className="list-card__meta">
                          <span className="badge">
                            {humanizeLabel(candidate.improvement_type)}
                          </span>
                          <span className={`badge badge--${candidate.status === 'pending_review' ? 'pending' : candidate.status}`}>
                            {humanizeLabel(candidate.status)}
                          </span>
                        </div>

                        <strong className="list-card__title">{candidate.title}</strong>
                        <p>{candidate.description}</p>

                        <div className="list-card__facts">
                          <span>Occurrences: {candidate.occurrence_count}</span>
                          <span>Confidence: {(candidate.confidence * 100).toFixed(1)}%</span>
                          <span>Evidence records: {candidate.evidence.length}</span>
                          <span>Created: <RecordTime seconds={candidate.created_at} /></span>
                          {candidate.reviewed_at !== null && (
                            <span>Reviewed: <RecordTime seconds={candidate.reviewed_at} /></span>
                          )}
                        </div>

                        {candidate.status === 'pending_review' && canReviewCandidates && (
                          <div className="button-row">
                            <button
                              type="button"
                              className="button"
                              disabled={reviewingCandidateId !== null}
                              onClick={() => void handleReview(candidate, 'approve')}
                            >
                              {isReviewing ? 'Saving…' : 'Approve'}
                            </button>
                            <button
                              type="button"
                              className="button button--danger"
                              disabled={reviewingCandidateId !== null}
                              onClick={() => void handleReview(candidate, 'reject')}
                            >
                              Reject
                            </button>
                          </div>
                        )}
                      </article>
                    )
                  })
                )}
              </div>
            </section>

            <section className="panel">
              <h3 className="section-title">Discovered patterns</h3>

              <div className="card-stack">
                {patterns.length === 0 ? (
                  <StatePanel
                    compact
                    title="No learning patterns yet"
                    description="Patterns are discovered once enough related evidence is collected from calls."
                  />
                ) : (
                  patterns.map((pattern) => (
                    <article key={pattern.pattern_id} className="list-card">
                      <div className="list-card__meta">
                        <span className="badge">{humanizeLabel(pattern.component)}</span>
                      </div>
                      <strong className="list-card__title">{pattern.description}</strong>
                      <p>Suggested improvement: {pattern.suggested_improvement}</p>
                      <div className="list-card__facts">
                        <span>Occurrences: {pattern.occurrence_count}</span>
                        <span>Evidence records: {pattern.evidence_ids.length}</span>
                      </div>
                    </article>
                  ))
                )}
              </div>
            </section>
          </div>

          <section className="panel">
            <div className="section-heading">
              <h3 className="section-title">Active improvements</h3>
              {!canReviewCandidates && improvements.length > 0 && (
                <span className="badge">Deactivation requires Supervisor or Admin</span>
              )}
            </div>

            {improvementError && (
              <StatePanel
                variant="error"
                compact
                title="Deactivation failed"
                description={improvementError}
              />
            )}

            <div className="card-stack">
              {improvements.length === 0 ? (
                <StatePanel
                  compact
                  title="No active improvements"
                  description="Approved candidates appear here and start guiding the live AI immediately."
                />
              ) : (
                improvements.map((improvement) => {
                  const isActive = improvement.status === 'active'

                  return (
                    <article key={improvement.improvement_id} className="list-card">
                      <div className="list-card__meta">
                        <span className="badge">{humanizeLabel(improvement.component)}</span>
                        <span className={`badge${isActive ? ' badge--active' : ''}`}>
                          {humanizeLabel(improvement.status)}
                        </span>
                      </div>

                      <p>{improvement.guidance}</p>

                      <div className="list-card__facts">
                        <span>Used on {improvement.usage_count} AI output(s)</span>
                        <span>
                          Feedback on calls where it was used: {improvement.feedback_count}
                        </span>
                        <span>Activated: <RecordTime seconds={improvement.activated_at} /></span>
                        {improvement.deactivated_at !== null && (
                          <span>
                            Deactivated: <RecordTime seconds={improvement.deactivated_at} />
                          </span>
                        )}
                      </div>

                      {isActive && canReviewCandidates && (
                        <div className="button-row">
                          <button
                            type="button"
                            className="button button--danger"
                            disabled={deactivatingId !== null}
                            onClick={() => void handleDeactivate(improvement)}
                          >
                            {deactivatingId === improvement.improvement_id
                              ? 'Deactivating…'
                              : 'Deactivate'}
                          </button>
                        </div>
                      )}
                    </article>
                  )
                })
              )}
            </div>
          </section>

          <section className="panel">
            <div className="section-heading">
              <h3 className="section-title">Learning evidence</h3>
              {evidence.length > 0 && (
                <span className="customer-panel__muted">
                  {visibleEvidence.length} of {evidence.length}
                </span>
              )}
            </div>

            {presentComponents.length > 0 && (
              <fieldset className="call-filters__checks evidence-filter">
                <legend>Show</legend>
                {presentComponents.map((component) => (
                  <label
                    key={component}
                    className={`call-filters__check evidence-filter__option evidence-tone--${component}`}
                  >
                    <input
                      type="checkbox"
                      checked={evidenceComponents.includes(component)}
                      onChange={(event) =>
                        setEvidenceComponents((current) =>
                          event.target.checked
                            ? [...current.filter((c) => c !== component), component]
                            : current.filter((c) => c !== component),
                        )
                      }
                    />
                    {humanizeLabel(component)}
                  </label>
                ))}
              </fieldset>
            )}

            <div className="card-stack">
              {evidence.length === 0 ? (
                <StatePanel
                  compact
                  title="No learning evidence yet"
                  description="Evidence is recorded automatically as calls are analysed."
                />
              ) : (
                visibleEvidence.map((item) => (
                  <article
                    key={item.evidence_id}
                    className={`list-card evidence-card evidence-tone--${item.component}`}
                  >
                    <div className="evidence-card__top">
                      <div className="list-card__meta">
                        <span className="badge evidence-card__component">
                          {humanizeLabel(item.component)}
                        </span>
                        {/* Predictions are the default; only other kinds are tagged. */}
                        {item.evidence_type !== 'ai_prediction' && (
                          <span className="badge">{humanizeLabel(item.evidence_type)}</span>
                        )}
                      </div>
                      <div className="list-card__facts evidence-card__source">
                        <span>
                          Customer:{' '}
                          <Link
                            className="text-link"
                            to={`/post-call-analysis?call_id=${encodeURIComponent(item.call_id)}`}
                            title={`Call ${item.call_id}`}
                          >
                            {evidenceCaller(item)}
                          </Link>
                        </span>
                        <span>Recorded: <RecordTime seconds={item.created_at} /></span>
                      </div>
                    </div>

                    <p>{item.description}</p>

                    {(item.expected_value ||
                      item.human_correction ||
                      (item.actual_value && item.actual_value !== item.description)) && (
                      <div className="list-card__facts">
                        {item.expected_value && <span>Expected: {item.expected_value}</span>}
                        {/* A prediction's description already is its value. */}
                        {item.actual_value && item.actual_value !== item.description && (
                          <span>Actual: {item.actual_value}</span>
                        )}
                        {item.human_correction && (
                          <span>Human correction: {item.human_correction}</span>
                        )}
                      </div>
                    )}
                  </article>
                ))
              )}
            </div>
          </section>

          <EmergingComplaintsPanel canReview={canReviewCandidates} />
        </>
      )}
    </section>
  )
}
