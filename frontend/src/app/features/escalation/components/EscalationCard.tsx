import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RecordTime } from '../../../components/RecordTime'

import { ApiError } from '../../../api/errors'
import { humanizeLabel } from '../../../format/text'
import { toEscalationViewModel } from '../adapters/toEscalationViewModel'
import { escalationRestService } from '../services/escalationRestService'

import type { EscalationLevel } from '../types/dto'
import type { EscalationViewModel } from '../types/view-models'

const LEVEL_BADGES: Record<EscalationLevel, string> = {
  watch: 'badge--warning',
  high: 'badge--danger',
  critical: 'badge--danger',
}

export function EscalationLevelBadge({ level }: { level: EscalationLevel }) {
  return (
    <span className={`badge ${LEVEL_BADGES[level]}`}>
      {level === 'critical' ? 'Critical escalation' : `${humanizeLabel(level)} escalation`}
    </span>
  )
}

type EscalationCardProps = {
  escalation: EscalationViewModel | null
  isCallActive?: boolean
  // Supervisors and admins can acknowledge and resolve.
  canManage?: boolean
  showCallLink?: boolean
  // Live view: whether the call is escalating and why, without the quoted
  // transcript or the timeline.
  compact?: boolean
  onUpdated?: (escalation: EscalationViewModel) => void
}

export function EscalationCard({
  escalation,
  isCallActive = false,
  canManage = false,
  showCallLink = false,
  compact = false,
  onUpdated,
}: EscalationCardProps) {
  const [isResolving, setIsResolving] = useState(false)
  const [note, setNote] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!escalation) {
    return (
      <section className="panel escalation-card escalation-card--calm">
        {compact ? (
          <h4 className="live-call__panel-title">Escalation</h4>
        ) : (
          <p className="panel__label">Escalation</p>
        )}
        <p className="customer-panel__muted">
          {isCallActive
            ? 'No signs of escalation so far.'
            : 'This call did not escalate.'}
        </p>
      </section>
    )
  }

  const act = async (action: () => Promise<Parameters<typeof toEscalationViewModel>[0]>) => {
    setIsSaving(true)
    setError(null)
    try {
      const updated = toEscalationViewModel(await action())
      setIsResolving(false)
      setNote('')
      onUpdated?.(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to update the escalation.')
    } finally {
      setIsSaving(false)
    }
  }

  const isResolved = escalation.status === 'resolved'

  return (
    <section
      className={`panel escalation-card escalation-card--${escalation.level}${isResolved ? ' escalation-card--resolved' : ''}`}
      aria-live="polite"
    >
      <div className="escalation-card__header">
        <div className="escalation-card__title">
          {compact ? (
            <h4 className="live-call__panel-title">Escalation</h4>
          ) : (
            <p className="panel__label">Escalation</p>
          )}
          {showCallLink ? (
            <Link
              className="text-link escalation-card__call"
              to={`/live-call?call_id=${encodeURIComponent(escalation.callId)}`}
              title={`Call ${escalation.callId}`}
            >
              Call Transcript
            </Link>
          ) : null}
        </div>
        <div className="escalation-card__badges">
          <EscalationLevelBadge level={escalation.level} />
          <span className={`badge${isResolved ? ' badge--success' : ''}`}>
            {humanizeLabel(escalation.status)}
          </span>
        </div>
      </div>

      <ul className="escalation-card__signals">
        {escalation.signals.map((signal) => (
          <li key={signal.type}>
            <strong>{signal.description}</strong>
            {!compact && signal.evidence && <q>{signal.evidence}</q>}
          </li>
        ))}
      </ul>

      {!compact && (
        <div className="list-card__facts">
          <span>
            <strong>Detected:</strong> <RecordTime seconds={escalation.firstDetectedAt} />
          </span>
          {escalation.acknowledgedBy && escalation.acknowledgedAt !== null && (
            <span>
              <strong>Acknowledged</strong> by {escalation.acknowledgedBy},{' '}
              <RecordTime seconds={escalation.acknowledgedAt} />
            </span>
          )}
          {escalation.resolvedBy && escalation.resolvedAt !== null && (
            <span>
              <strong>Resolved</strong> by {escalation.resolvedBy},{' '}
              <RecordTime seconds={escalation.resolvedAt} />
            </span>
          )}
        </div>
      )}

      {!compact && escalation.resolutionNote && <p className="summary-delivery__message">{escalation.resolutionNote}</p>}

      {canManage && isResolving && (
        <div className="escalation-card__resolve">
          <label htmlFor={`resolve-note-${escalation.callId}`}>What was done? (optional)</label>
          <textarea
            id={`resolve-note-${escalation.callId}`}
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
              onClick={() => void act(() => escalationRestService.resolve(escalation.callId, note))}
            >
              {isSaving ? 'Saving…' : 'Mark resolved'}
            </button>
            <button
              type="button"
              className="button button--secondary"
              disabled={isSaving}
              onClick={() => setIsResolving(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {canManage && !isResolved && !isResolving && (
        <div className="escalation-card__footer">
          {escalation.status === 'open' && (
            <button
              type="button"
              className="button"
              disabled={isSaving}
              onClick={() => void act(() => escalationRestService.acknowledge(escalation.callId))}
            >
              {isSaving ? 'Saving…' : 'Acknowledge'}
            </button>
          )}
          <button
            type="button"
            className="button button--secondary"
            disabled={isSaving}
            onClick={() => setIsResolving(true)}
          >
            Resolve
          </button>
        </div>
      )}

      {error && (
        <p className="review-form__error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
