import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import { formatRecordTimestamp } from '../../../format/time'
import { emergingComplaintRestService } from '../services/complaintRestService'

import type {
  DiscoveryRunDto,
  EmergingComplaintDto,
  EmergingComplaintStatus,
} from '../types/dto'

type Filter = EmergingComplaintStatus | 'all'

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'pending_review', label: 'Pending review' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'all', label: 'All' },
]

const STATUS_BADGES: Record<EmergingComplaintStatus, string> = {
  pending_review: 'badge--pending',
  accepted: 'badge--approved',
  rejected: 'badge--rejected',
}

const STATUS_LABELS: Record<EmergingComplaintStatus, string> = {
  pending_review: 'Pending review',
  accepted: 'Accepted',
  rejected: 'Rejected',
}

const EVIDENCE_PREVIEW = 3
const CALL_LINK_PREVIEW = 6

function describeRun(run: DiscoveryRunDto): string {
  const when = formatRecordTimestamp(run.ran_at)
  if (run.skipped_reason) {
    return `Last run ${when}: ${run.skipped_reason}`
  }
  return `Last run ${when}: read ${run.calls_scanned} completed calls, found ${run.candidates_found} theme${run.candidates_found === 1 ? '' : 's'} (${run.new_candidates} new).`
}

type CandidateCardProps = {
  candidate: EmergingComplaintDto
  canReview: boolean
  onReviewed: (candidate: EmergingComplaintDto) => void
}

function CandidateCard({ candidate, canReview, onReviewed }: CandidateCardProps) {
  const [decision, setDecision] = useState<EmergingComplaintStatus | null>(null)
  const [note, setNote] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAllEvidence, setShowAllEvidence] = useState(false)

  const submit = async (chosen: EmergingComplaintStatus) => {
    setIsSaving(true)
    setError(null)
    try {
      const reviewed = await emergingComplaintRestService.review(
        candidate.candidate_id,
        chosen,
        note,
      )
      setDecision(null)
      setNote('')
      onReviewed(reviewed)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to save the review.')
    } finally {
      setIsSaving(false)
    }
  }

  const evidence = showAllEvidence
    ? candidate.evidence
    : candidate.evidence.slice(0, EVIDENCE_PREVIEW)
  const noteId = `emerging-note-${candidate.candidate_id}`

  return (
    <article className="list-card">
      <div className="section-heading complaint-card__heading">
        <strong className="list-card__title">{candidate.proposed_name}</strong>
        <div className="list-card__meta">
          <span className="badge">
            {candidate.call_ids.length || candidate.occurrence_count} calls
          </span>
          <span className="badge">{Math.round(candidate.confidence * 100)}% confidence</span>
          <span className={`badge ${STATUS_BADGES[candidate.status]}`}>
            {STATUS_LABELS[candidate.status]}
          </span>
        </div>
      </div>

      <p>{candidate.description}</p>

      <ul className="escalation-card__signals">
        {evidence.map((quote, index) => (
          <li key={`${index}-${quote}`}>
            <q>{quote}</q>
          </li>
        ))}
      </ul>
      {candidate.evidence.length > EVIDENCE_PREVIEW && (
        <button
          type="button"
          className="text-link customer-panel__more"
          onClick={() => setShowAllEvidence((current) => !current)}
        >
          {showAllEvidence ? 'Show fewer quotes' : `Show all ${candidate.evidence.length} quotes`}
        </button>
      )}

      <div className="list-card__facts">
        {candidate.related_category && <span>Related to: {candidate.related_category}</span>}
        <span>First seen: {formatRecordTimestamp(candidate.first_seen_at)}</span>
        <span>Last seen: {formatRecordTimestamp(candidate.last_seen_at)}</span>
        {candidate.call_ids.length > 0 && (
          <span>
            Calls:{' '}
            {candidate.call_ids.slice(0, CALL_LINK_PREVIEW).map((callId, index) => (
              <span key={callId}>
                {index > 0 && ', '}
                <Link
                  className="text-link"
                  to={`/post-call-analysis?call_id=${encodeURIComponent(callId)}`}
                >
                  {callId}
                </Link>
              </span>
            ))}
            {candidate.call_ids.length > CALL_LINK_PREVIEW &&
              ` and ${candidate.call_ids.length - CALL_LINK_PREVIEW} more`}
          </span>
        )}
        {candidate.reviewed_by && candidate.reviewed_at !== null && (
          <span>
            Reviewed by {candidate.reviewed_by}, {formatRecordTimestamp(candidate.reviewed_at)}
          </span>
        )}
      </div>

      {candidate.review_note && (
        <p className="summary-delivery__message">{candidate.review_note}</p>
      )}

      {canReview && decision === null && (
        <div className="button-row">
          {candidate.status === 'pending_review' ? (
            <>
              <button
                type="button"
                className="button"
                disabled={isSaving}
                onClick={() => setDecision('accepted')}
              >
                Accept theme
              </button>
              <button
                type="button"
                className="button button--secondary"
                disabled={isSaving}
                onClick={() => setDecision('rejected')}
              >
                Reject
              </button>
            </>
          ) : (
            <button
              type="button"
              className="button button--secondary"
              disabled={isSaving}
              onClick={() => void submit('pending_review')}
            >
              {isSaving ? 'Saving…' : 'Reopen review'}
            </button>
          )}
        </div>
      )}

      {canReview && decision !== null && (
        <div className="escalation-card__resolve">
          <label htmlFor={noteId}>
            {decision === 'accepted'
              ? 'What should happen about it? (optional)'
              : 'Why is it not a real theme? (optional)'}
          </label>
          <textarea
            id={noteId}
            rows={2}
            maxLength={500}
            value={note}
            disabled={isSaving}
            onChange={(event) => setNote(event.target.value)}
          />
          <div className="button-row">
            <button
              type="button"
              className="button"
              disabled={isSaving}
              onClick={() => void submit(decision)}
            >
              {isSaving ? 'Saving…' : decision === 'accepted' ? 'Accept theme' : 'Reject'}
            </button>
            <button
              type="button"
              className="button button--secondary"
              disabled={isSaving}
              onClick={() => setDecision(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="review-form__error" role="alert">
          {error}
        </p>
      )}
    </article>
  )
}

type EmergingComplaintsPanelProps = {
  canReview: boolean
}

// Complaint themes that recur across calls but match no known category.
export function EmergingComplaintsPanel({ canReview }: EmergingComplaintsPanelProps) {
  const [filter, setFilter] = useState<Filter>('pending_review')
  const [candidates, setCandidates] = useState<EmergingComplaintDto[]>([])
  const [lastRun, setLastRun] = useState<DiscoveryRunDto | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isDiscovering, setIsDiscovering] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (current: Filter) => {
    try {
      const data = await emergingComplaintRestService.list(
        current === 'all' ? undefined : current,
      )
      setCandidates(data.candidates)
      setLastRun(data.last_run)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to load emerging complaints.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const refresh = () => {
      if (!cancelled) {
        void load(filter)
      }
    }
    refresh()
    return () => {
      cancelled = true
    }
  }, [filter, load])

  const handleDiscover = async () => {
    setIsDiscovering(true)
    setError(null)
    try {
      setLastRun(await emergingComplaintRestService.discover())
      await load(filter)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Discovery failed.')
    } finally {
      setIsDiscovering(false)
    }
  }

  const handleReviewed = (reviewed: EmergingComplaintDto) => {
    setCandidates((current) =>
      filter !== 'all' && reviewed.status !== filter
        ? current.filter((item) => item.candidate_id !== reviewed.candidate_id)
        : current.map((item) =>
            item.candidate_id === reviewed.candidate_id ? reviewed : item,
          ),
    )
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h3 className="section-title">Emerging complaints</h3>
          <p className="customer-panel__muted">
            Complaint themes that recur across completed calls but match none of the known
            categories.
          </p>
        </div>
        {canReview && (
          <button
            type="button"
            className="button"
            disabled={isDiscovering}
            onClick={() => void handleDiscover()}
          >
            {isDiscovering ? 'Looking for themes…' : 'Run discovery now'}
          </button>
        )}
      </div>

      <div className="section-heading">
        <div className="button-row" role="tablist" aria-label="Emerging complaint status">
          {FILTERS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={filter === item.value}
              className={filter === item.value ? 'button' : 'button button--secondary'}
              onClick={() => {
                if (item.value !== filter) {
                  setIsLoading(true)
                  setFilter(item.value)
                }
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
        {lastRun && <span className="customer-panel__muted">{describeRun(lastRun)}</span>}
      </div>

      {isLoading && <StatePanel compact variant="loading" title="Loading emerging complaints…" />}

      {!isLoading && error && (
        <StatePanel compact variant="error" title="Could not load emerging complaints" description={error} />
      )}

      {!isLoading && !error && candidates.length === 0 && (
        <StatePanel
          compact
          title={filter === 'pending_review' ? 'Nothing to review' : 'No themes here'}
          description="Discovery runs after every completed call. A theme appears once customers raise the same issue on at least two calls."
        />
      )}

      {!isLoading && !error && candidates.length > 0 && (
        <div className="card-stack">
          {candidates.map((candidate) => (
            <CandidateCard
              key={candidate.candidate_id}
              candidate={candidate}
              canReview={canReview}
              onReviewed={handleReviewed}
            />
          ))}
        </div>
      )}
    </section>
  )
}
