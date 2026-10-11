import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { RecordTime } from '../components/RecordTime'
import { useAuth } from '../auth/useAuth'
import { ApiError } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { humanizeLabel } from '../format/text'

import { CorrectionsPanel } from '../features/ai-improvement/components/CorrectionsPanel'
import { learningRestService } from '../features/ai-improvement/services/learningRestService'
import { EmergingComplaintsPanel } from '../features/complaints/components/EmergingComplaintsPanel'

import type {
  ActiveImprovementDto,
  ImprovementEffect,
  LearningCandidateDto,
} from '../features/ai-improvement/types/dto'

// How often reviewers corrected the output since the improvement went live,
// compared with before.
const EFFECT_LABELS: Record<ImprovementEffect, string> = {
  not_enough_data: 'Effect: not enough calls yet',
  better: 'Effect: corrected less often',
  no_change: 'Effect: no change',
  worse: 'Effect: corrected more often',
}

// A supervisor's page has three parts; an executive sees the first only.
const TABS = [
  { id: 'improvements', name: 'Improvements' },
  { id: 'themes', name: 'New complaint themes' },
  { id: 'corrections', name: 'Corrections' },
] as const
type TabId = (typeof TABS)[number]['id']
const TAB_PARAM = 'tab'

type ReviewNotice = {
  candidateTitle: string
  action: 'approve' | 'reject'
}

export function AiImprovementCenterPage() {
  const { session } = useAuth()
  const canReview = session?.role === 'SUPERVISOR'
  const [searchParams, setSearchParams] = useSearchParams()
  const requested = searchParams.get(TAB_PARAM)
  const tab: TabId =
    canReview && TABS.some((item) => item.id === requested) ? (requested as TabId) : 'improvements'

  const [candidates, setCandidates] = useState<LearningCandidateDto[]>([])
  const [improvements, setImprovements] = useState<ActiveImprovementDto[]>([])
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null)
  const [improvementError, setImprovementError] = useState<string | null>(null)

  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [reviewNotice, setReviewNotice] = useState<ReviewNotice | null>(null)
  const [reviewingCandidateId, setReviewingCandidateId] = useState<string | null>(null)
  const [showReviewed, setShowReviewed] = useState(false)
  const [showPast, setShowPast] = useState(false)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const [candidateData, improvementData] = await Promise.all([
          learningRestService.listCandidates(),
          learningRestService.listImprovements(),
        ])
        if (cancelled) return
        setCandidates(candidateData)
        setImprovements(improvementData)
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Unable to load AI improvement data.')
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [])

  const handleReview = async (candidate: LearningCandidateDto, action: 'approve' | 'reject') => {
    setReviewingCandidateId(candidate.candidate_id)
    setReviewError(null)
    setReviewNotice(null)

    try {
      const updatedCandidate =
        action === 'approve'
          ? await learningRestService.approveCandidate(candidate.candidate_id)
          : await learningRestService.rejectCandidate(candidate.candidate_id)

      setCandidates((current) =>
        current.map((item) =>
          item.candidate_id === candidate.candidate_id ? updatedCandidate : item,
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
      setReviewError(
        err instanceof ApiError ? err.message : `Unable to ${action} the suggested improvement.`,
      )
    } finally {
      setReviewingCandidateId(null)
    }
  }

  const handleDeactivate = async (improvement: ActiveImprovementDto) => {
    setDeactivatingId(improvement.improvement_id)
    setImprovementError(null)

    try {
      const updated = await learningRestService.deactivateImprovement(improvement.improvement_id)
      setImprovements((current) =>
        current.map((item) => (item.improvement_id === updated.improvement_id ? updated : item)),
      )
    } catch (err) {
      setImprovementError(
        err instanceof ApiError ? err.message : 'Unable to deactivate the improvement.',
      )
    } finally {
      setDeactivatingId(null)
    }
  }

  const pending = candidates.filter((candidate) => candidate.status === 'pending_review')
  const reviewed = candidates.filter((candidate) => candidate.status !== 'pending_review')
  const active = improvements.filter((improvement) => improvement.status === 'active')
  const past = improvements.filter((improvement) => improvement.status !== 'active')

  const candidateCard = (candidate: LearningCandidateDto) => {
    const isReviewing = reviewingCandidateId === candidate.candidate_id
    const isPending = candidate.status === 'pending_review'
    return (
      <article key={candidate.candidate_id} className="list-card">
        <div className="section-heading complaint-card__heading">
          <strong className="list-card__title">{candidate.title}</strong>
          <div className="list-card__meta">
            <span className="badge">{humanizeLabel(candidate.improvement_type)}</span>
            {!isPending && (
              <span className={`badge badge--${candidate.status}`}>
                {humanizeLabel(candidate.status)}
              </span>
            )}
          </div>
        </div>

        <p>{candidate.description}</p>

        <div className="list-card__facts">
          <span>Seen {candidate.occurrence_count} times</span>
          <span>
            Suggested: <RecordTime seconds={candidate.created_at} />
          </span>
          {candidate.reviewed_at !== null && (
            <span>
              Reviewed: <RecordTime seconds={candidate.reviewed_at} />
            </span>
          )}
        </div>

        {isPending && canReview && (
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
  }

  const improvementCard = (improvement: ActiveImprovementDto) => {
    const isActive = improvement.status === 'active'
    return (
      <article key={improvement.improvement_id} className="list-card">
        <div className="list-card__meta">
          <span className="badge">{humanizeLabel(improvement.component)}</span>
          {!isActive && <span className="badge">{humanizeLabel(improvement.status)}</span>}
          {canReview && <span className="badge">{EFFECT_LABELS[improvement.effect]}</span>}
        </div>

        <p>{improvement.guidance}</p>

        <div className="list-card__facts">
          <span>
            In use since: <RecordTime seconds={improvement.activated_at} />
          </span>
          {improvement.deactivated_at !== null && (
            <span>
              Switched off: <RecordTime seconds={improvement.deactivated_at} />
            </span>
          )}
          {canReview && (
            <span>
              Corrected before: {improvement.corrections_before} of {improvement.outputs_before}{' '}
              call(s); since: {improvement.corrections_after} of {improvement.outputs_after}
            </span>
          )}
        </div>

        {isActive && canReview && (
          <div className="button-row">
            <button
              type="button"
              className="button button--danger"
              disabled={deactivatingId !== null}
              onClick={() => void handleDeactivate(improvement)}
            >
              {deactivatingId === improvement.improvement_id ? 'Deactivating…' : 'Deactivate'}
            </button>
          </div>
        )}
      </article>
    )
  }

  const improvementsTab = (
    <>
      {isLoading && <StatePanel variant="loading" title="Loading AI improvement data…" />}

      {!isLoading && error && (
        <StatePanel variant="error" title="Could not load the improvements" description={error} />
      )}

      {!isLoading && !error && (
        <>
          <div className="kpi-grid">
            <article className="panel">
              <p className="panel__label">Waiting for review</p>
              <h3>{pending.length}</h3>
              <span>Suggested improvements a supervisor has not decided on</span>
            </article>
            <article className="panel">
              <p className="panel__label">In use</p>
              <h3>{active.length}</h3>
              <span>Improvements the AI follows on every call</span>
            </article>
          </div>

          <section className="panel">
            <div className="section-heading">
              <div>
                <h3 className="section-title">Suggested improvements</h3>
                <p className="customer-panel__muted">
                  When the same correction is made on several calls, it is suggested here.
                  {canReview
                    ? ' Approving one puts it to use at once: the AI is told to follow it on every call until it is deactivated.'
                    : ' A supervisor approves or rejects each one.'}
                </p>
              </div>
            </div>

            {reviewNotice && (
              <p className="inline-notice inline-notice--success" role="status">
                {reviewNotice.action === 'approve'
                  ? `“${reviewNotice.candidateTitle}” was approved and is now in use.`
                  : `“${reviewNotice.candidateTitle}” was rejected.`}
              </p>
            )}

            {reviewError && (
              <StatePanel variant="error" compact title="Review failed" description={reviewError} />
            )}

            <div className="card-stack">
              {pending.length === 0 ? (
                <StatePanel
                  compact
                  title="Nothing is waiting for review"
                  description="A suggestion appears when the same correction is made on at least two calls."
                />
              ) : (
                pending.map(candidateCard)
              )}
            </div>

            {canReview && reviewed.length > 0 && (
              <>
                <button
                  type="button"
                  className="text-link customer-panel__more"
                  onClick={() => setShowReviewed((current) => !current)}
                >
                  {showReviewed
                    ? 'Hide reviewed suggestions'
                    : `Show ${reviewed.length} reviewed suggestion${reviewed.length === 1 ? '' : 's'}`}
                </button>
                {showReviewed && <div className="card-stack">{reviewed.map(candidateCard)}</div>}
              </>
            )}
          </section>

          <section className="panel">
            <div className="section-heading">
              <div>
                <h3 className="section-title">
                  {canReview ? 'Improvements in use' : 'What the AI has been taught'}
                </h3>
                <p className="customer-panel__muted">
                  Guidance the AI is given on every call, each from an approved suggestion.
                </p>
              </div>
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
              {active.length === 0 ? (
                <StatePanel
                  compact
                  title="Nothing yet"
                  description="An approved suggestion appears here and guides the AI from the next call."
                />
              ) : (
                active.map(improvementCard)
              )}
            </div>

            {canReview && past.length > 0 && (
              <>
                <button
                  type="button"
                  className="text-link customer-panel__more"
                  onClick={() => setShowPast((current) => !current)}
                >
                  {showPast
                    ? 'Hide deactivated improvements'
                    : `Show ${past.length} deactivated improvement${past.length === 1 ? '' : 's'}`}
                </button>
                {showPast && <div className="card-stack">{past.map(improvementCard)}</div>}
              </>
            )}
          </section>
        </>
      )}
    </>
  )

  return (
    <section className="page-shell">
      {!canReview && (
        <p className="inline-notice">
          When you correct the AI on a finished call's page (under “Review AI output”), the
          correction is kept. If the same correction keeps coming up, it is suggested as an
          improvement, and once a supervisor approves it the AI follows it on every call.
        </p>
      )}

      {canReview && (
        <div className="report-views" role="tablist" aria-label="AI Improvement Center">
          {TABS.map(({ id, name }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={`report-views__tab${tab === id ? ' report-views__tab--active' : ''}`}
              onClick={() => setSearchParams(id === 'improvements' ? {} : { [TAB_PARAM]: id })}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      {tab === 'improvements' && improvementsTab}
      {tab === 'themes' && <EmergingComplaintsPanel canReview={canReview} />}
      {tab === 'corrections' && <CorrectionsPanel />}
    </section>
  )
}
