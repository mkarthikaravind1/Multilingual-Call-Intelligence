import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import { ApiError } from '../api/errors'

import { learningRestService } from '../features/ai-improvement/services/learningRestService'

import type {
  LearningCandidateDto,
  LearningEvidenceDto,
  LearningPatternDto,
} from '../features/ai-improvement/types/dto'

export function AiImprovementCenterPage() {
  const { session } = useAuth()
  const canReviewCandidates = session?.role === 'SUPERVISOR' || session?.role === 'ADMIN'
  const [candidates, setCandidates] = useState<LearningCandidateDto[]>([])
  const [patterns, setPatterns] = useState<LearningPatternDto[]>([])
  const [evidence, setEvidence] = useState<LearningEvidenceDto[]>([])

  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reviewingCandidateId, setReviewingCandidateId] =
    useState<string | null>(null)

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
    candidateId: string,
    action: 'approve' | 'reject',
  ) => {
    setReviewingCandidateId(candidateId)
    setError(null)

    try {
      const updatedCandidate =
        action === 'approve'
          ? await learningRestService.approveCandidate(candidateId)
          : await learningRestService.rejectCandidate(candidateId)

      setCandidates((currentCandidates) =>
        currentCandidates.map((candidate) =>
          candidate.candidate_id === candidateId
            ? updatedCandidate
            : candidate,
        ),
      )
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError(
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

  return (
    <section className="page-shell">
      <div className="page-shell__header">
        <div>
          <p className="eyebrow">Learning</p>
          <h2>AI improvement center</h2>
        </div>
      </div>

      {error && (
        <div className="live-call__error" role="alert">
          <strong>Learning center error</strong>
          <span>{error}</span>
        </div>
      )}

      {isLoading ? (
        <div className="panel">
          <p>Loading AI improvement data…</p>
        </div>
      ) : (
        <>
          <div className="page-shell__grid">
            <article className="panel">
              <p className="panel__label">Suggested improvements</p>
              <h3>{pendingCandidates.length}</h3>
              <span>Pending human review</span>
            </article>

            <article className="panel">
              <p className="panel__label">Approved improvements</p>
              <h3>{approvedCandidates.length}</h3>
              <span>Human-approved candidates</span>
            </article>

            <article className="panel">
              <p className="panel__label">Learning patterns</p>
              <h3>{patterns.length}</h3>
              <span>Patterns discovered from call evidence</span>
            </article>

            <article className="panel">
              <p className="panel__label">Learning evidence</p>
              <h3>{evidence.length}</h3>
              <span>Evidence records collected from calls</span>
            </article>
          </div>

          <div className="page-shell__grid">
            <section className="panel">
              <p className="panel__label">Improvement candidates</p>

              {candidates.length === 0 ? (
                <p>No improvement candidates are currently available.</p>
              ) : (
                <div className="info-list">
                  {candidates.map((candidate) => {
                    const isReviewing =
                      reviewingCandidateId === candidate.candidate_id

                    return (
                      <article
                        key={candidate.candidate_id}
                        className="panel"
                      >
                        <p className="panel__label">
                          {candidate.improvement_type}
                        </p>

                        <h3>{candidate.title}</h3>

                        <p>{candidate.description}</p>

                        <div className="info-list">
                          <span>
                            Status: {candidate.status}
                          </span>

                          <span>
                            Occurrences: {candidate.occurrence_count}
                          </span>

                          <span>
                            Confidence:{' '}
                            {(candidate.confidence * 100).toFixed(1)}%
                          </span>

                          <span>
                            Evidence records:{' '}
                            {candidate.evidence.length}
                          </span>
                        </div>

                        {candidate.status === 'pending_review' && canReviewCandidates && (
                          <div
                            className="live-call__call-selector"
                            style={{ marginTop: '1rem' }}
                          >
                            <button
                              type="button"
                              disabled={isReviewing}
                              onClick={() =>
                                void handleReview(
                                  candidate.candidate_id,
                                  'approve',
                                )
                              }
                            >
                              {isReviewing
                                ? 'Reviewing…'
                                : 'Approve'}
                            </button>

                            <button
                              type="button"
                              disabled={isReviewing}
                              onClick={() =>
                                void handleReview(
                                  candidate.candidate_id,
                                  'reject',
                                )
                              }
                            >
                              {isReviewing
                                ? 'Reviewing…'
                                : 'Reject'}
                            </button>
                          </div>
                        )}
                      </article>
                    )
                  })}
                </div>
              )}
            </section>

            <section className="panel">
              <p className="panel__label">Discovered patterns</p>

              {patterns.length === 0 ? (
                <p>No learning patterns are currently available.</p>
              ) : (
                <div className="info-list">
                  {patterns.map((pattern) => (
                    <article
                      key={pattern.pattern_id}
                      className="panel"
                    >
                      <p className="panel__label">
                        {pattern.component}
                      </p>

                      <h3>
                        {pattern.description}
                      </h3>

                      <span>
                        Occurrences: {pattern.occurrence_count}
                      </span>

                      <p>
                        Suggested improvement:{' '}
                        {pattern.suggested_improvement}
                      </p>

                      <span>
                        Evidence records:{' '}
                        {pattern.evidence_ids.length}
                      </span>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </div>

          <section className="panel">
            <p className="panel__label">Learning evidence</p>

            {evidence.length === 0 ? (
              <p>No learning evidence is currently available.</p>
            ) : (
              <div className="info-list">
                {evidence.map((item) => (
                  <article
                    key={item.evidence_id}
                    className="panel"
                  >
                    <p className="panel__label">
                      {item.component} · {item.evidence_type}
                    </p>

                    <p>{item.description}</p>

                    <div className="info-list">
                      <span>
                        Call:{' '}
                        <Link to={`/post-call-analysis?call_id=${encodeURIComponent(item.call_id)}`}>
                          {item.call_id}
                        </Link>
                      </span>

                      {item.expected_value && (
                        <span>
                          Expected: {item.expected_value}
                        </span>
                      )}

                      {item.actual_value && (
                        <span>
                          Actual: {item.actual_value}
                        </span>
                      )}

                      {item.human_correction && (
                        <span>
                          Human correction:{' '}
                          {item.human_correction}
                        </span>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </section>
  )
}