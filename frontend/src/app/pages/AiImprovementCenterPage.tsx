import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import { ApiError } from '../api/errors'
import { IntegrationPendingCard } from '../components/IntegrationPendingCard'
import { StatePanel } from '../components/StatePanel'
import { humanizeLabel } from '../format/text'
import { formatRecordTimestamp } from '../format/time'

import { learningRestService } from '../features/ai-improvement/services/learningRestService'

import type {
  LearningCandidateDto,
  LearningEvidenceDto,
  LearningPatternDto,
} from '../features/ai-improvement/types/dto'

const EVIDENCE_PAGE_SIZE = 25

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

  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [reviewNotice, setReviewNotice] = useState<ReviewNotice | null>(null)
  const [reviewingCandidateId, setReviewingCandidateId] =
    useState<string | null>(null)
  const [showAllEvidence, setShowAllEvidence] = useState(false)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const [candidateData, patternData, evidenceData] = await Promise.all([
          learningRestService.listCandidates(),
          learningRestService.listPatterns(),
          learningRestService.listEvidence(),
        ])

        if (cancelled) {
          return
        }

        setCandidates(candidateData)
        setPatterns(patternData)
        setEvidence(evidenceData)
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

  const pendingCandidates = candidates.filter(
    (candidate) => candidate.status === 'pending_review',
  )

  const approvedCandidates = candidates.filter(
    (candidate) => candidate.status === 'approved',
  )

  const sortedEvidence = [...evidence].sort((a, b) => b.created_at - a.created_at)
  const visibleEvidence = showAllEvidence
    ? sortedEvidence
    : sortedEvidence.slice(0, EVIDENCE_PAGE_SIZE)

  const metrics = [
    { label: 'Suggested improvements', value: pendingCandidates.length, caption: 'Pending human review' },
    { label: 'Approved improvements', value: approvedCandidates.length, caption: 'Review decision recorded' },
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
                Approving a candidate records the review decision. Applying
                approved improvements to the live AI at runtime is not yet
                available.
              </p>

              {reviewNotice && (
                <p className="inline-notice inline-notice--success spaced-top" role="status">
                  “{reviewNotice.candidateTitle}” was{' '}
                  {reviewNotice.action === 'approve' ? 'approved' : 'rejected'}. The
                  decision has been recorded.
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
                    description="Candidates appear here once the learning engine proposes them from call evidence."
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
                          <span>Created: {formatRecordTimestamp(candidate.created_at)}</span>
                          {candidate.reviewed_at !== null && (
                            <span>Reviewed: {formatRecordTimestamp(candidate.reviewed_at)}</span>
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
              <h3 className="section-title">Learning evidence</h3>
              {evidence.length > EVIDENCE_PAGE_SIZE && (
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => setShowAllEvidence((current) => !current)}
                >
                  {showAllEvidence
                    ? `Show latest ${EVIDENCE_PAGE_SIZE}`
                    : `Show all ${evidence.length}`}
                </button>
              )}
            </div>

            <div className="card-stack">
              {evidence.length === 0 ? (
                <StatePanel
                  compact
                  title="No learning evidence yet"
                  description="Evidence is recorded automatically as calls are analysed."
                />
              ) : (
                visibleEvidence.map((item) => (
                  <article key={item.evidence_id} className="list-card">
                    <div className="list-card__meta">
                      <span className="badge">{humanizeLabel(item.component)}</span>
                      <span className="badge">{humanizeLabel(item.evidence_type)}</span>
                    </div>

                    <p>{item.description}</p>

                    <div className="list-card__facts">
                      <span>
                        Call:{' '}
                        <Link
                          className="text-link"
                          to={`/post-call-analysis?call_id=${encodeURIComponent(item.call_id)}`}
                        >
                          {item.call_id}
                        </Link>
                      </span>
                      {item.expected_value && <span>Expected: {item.expected_value}</span>}
                      {item.actual_value && <span>Actual: {item.actual_value}</span>}
                      {item.human_correction && (
                        <span>Human correction: {item.human_correction}</span>
                      )}
                      <span>Recorded: {formatRecordTimestamp(item.created_at)}</span>
                    </div>
                  </article>
                ))
              )}
            </div>
          </section>

          <section className="panel">
            <p className="panel__label">Upcoming learning capabilities</p>
            <div className="integration-grid">
              <IntegrationPendingCard
                title="Active improvement effectiveness"
                description="Effectiveness of improvements running in the live AI will appear once approved improvements can be activated at runtime."
              />
              <IntegrationPendingCard
                title="Emerging complaints"
                description="New complaint themes discovered across calls will appear once emerging-complaint discovery is enabled in the backend."
              />
            </div>
          </section>
        </>
      )}
    </section>
  )
}
