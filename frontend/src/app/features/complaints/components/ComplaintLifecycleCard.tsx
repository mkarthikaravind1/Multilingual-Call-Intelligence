import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../../../api/errors'
import { formatRecordTimestamp } from '../../../format/time'
import { complaintRestService } from '../services/complaintRestService'

import type {
  ComplaintAction,
  ComplaintDto,
  ComplaintEventDto,
  ComplaintStatus,
} from '../types/dto'

const STATUS_LABELS: Record<ComplaintStatus, string> = {
  raised: 'Raised',
  detected: 'Detected',
  probed: 'Probed',
  covered: 'Covered',
  resolved: 'Resolved',
  unresolved: 'Unresolved',
  follow_up: 'Follow-up',
}

const STATUS_BADGES: Record<ComplaintStatus, string> = {
  raised: 'badge--pending',
  detected: 'badge--pending',
  probed: 'badge--pending',
  covered: 'badge--pending',
  resolved: 'badge--success',
  unresolved: 'badge--danger',
  follow_up: 'badge--warning',
}

const ACTIONS: Record<ComplaintAction, { label: string; prompt: string; primary: boolean }> = {
  resolved: { label: 'Mark resolved', prompt: 'How was it resolved? (optional)', primary: true },
  unresolved: {
    label: 'Mark unresolved',
    prompt: 'Why could it not be resolved? (optional)',
    primary: false,
  },
  follow_up: {
    label: 'Schedule follow-up',
    prompt: 'What needs to happen next? (optional)',
    primary: false,
  },
}

// The in-call stages every complaint moves through, then its outcome.
const IN_CALL_STAGES: ComplaintStatus[] = ['detected', 'probed', 'covered']

export function ComplaintStatusBadge({ status }: { status: ComplaintStatus }) {
  return <span className={`badge ${STATUS_BADGES[status]}`}>{STATUS_LABELS[status]}</span>
}

function actorLabel(actor: string) {
  return actor === 'system' ? 'Call analysis' : actor
}

function LifecycleTrack({ complaint }: { complaint: ComplaintDto }) {
  const reached = new Set<ComplaintStatus>([
    ...complaint.events.map((event) => event.status),
    complaint.status,
  ])
  const outcome = [...complaint.events]
    .reverse()
    .find((event) => event.status === 'resolved' || event.status === 'unresolved')?.status
  const stages: { key: string; label: string; state: 'done' | 'current' | 'todo' }[] =
    IN_CALL_STAGES.map((status) => ({
      key: status,
      label: STATUS_LABELS[status],
      state: complaint.status === status ? 'current' : reached.has(status) ? 'done' : 'todo',
    }))

  stages.push({
    key: 'outcome',
    label: outcome ? STATUS_LABELS[outcome] : 'Outcome',
    state: complaint.status === outcome ? 'current' : outcome ? 'done' : 'todo',
  })
  if (reached.has('follow_up') || complaint.follow_up_required) {
    stages.push({
      key: 'follow_up',
      label: 'Follow-up',
      state:
        complaint.status === 'follow_up'
          ? 'current'
          : reached.has('follow_up')
            ? 'done'
            : 'todo',
    })
  }

  return (
    <ol className="complaint-track" aria-label="Complaint lifecycle">
      {stages.map((stage) => (
        <li
          key={stage.key}
          className={`complaint-track__step complaint-track__step--${stage.state}`}
          aria-current={stage.state === 'current' ? 'step' : undefined}
        >
          {stage.label}
        </li>
      ))}
    </ol>
  )
}

function History({ events }: { events: ComplaintEventDto[] }) {
  return (
    <ol className="complaint-history">
      {events.map((event, index) => (
        <li key={`${event.at}-${index}`}>
          <div className="complaint-history__line">
            <ComplaintStatusBadge status={event.status} />
            <span>
              {actorLabel(event.actor)} · {formatRecordTimestamp(event.at)}
            </span>
          </div>
          {event.note && <p className="complaint-history__note">{event.note}</p>}
        </li>
      ))}
    </ol>
  )
}

type ComplaintLifecycleCardProps = {
  complaint: ComplaintDto
  showCallLink?: boolean
  canAct?: boolean
  // Compact cards (e.g. a customer's older complaints) start with less detail.
  compact?: boolean
  onUpdated?: (complaint: ComplaintDto) => void
}

export function ComplaintLifecycleCard({
  complaint,
  showCallLink = false,
  canAct = true,
  compact = false,
  onUpdated,
}: ComplaintLifecycleCardProps) {
  const [pendingAction, setPendingAction] = useState<ComplaintAction | null>(null)
  const [note, setNote] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  const submit = async (action: ComplaintAction) => {
    setIsSaving(true)
    setError(null)
    try {
      const updated = await complaintRestService.updateStatus(
        complaint.complaint_id,
        action,
        note,
      )
      setPendingAction(null)
      setNote('')
      onUpdated?.(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to update the complaint.')
    } finally {
      setIsSaving(false)
    }
  }

  // Only notes people wrote: the system's own note ("the call ended before
  // this complaint was resolved…") repeats the Needs follow-up badge, and
  // stays visible in the history.
  const lastNote = [...complaint.events]
    .reverse()
    .find((event) => event.note && event.actor !== 'system')
  const noteId = `complaint-note-${complaint.complaint_id.replace(/[^\w-]/g, '-')}`

  return (
    <article
      className={[
        'list-card',
        'complaint-card',
        complaint.is_open ? '' : 'complaint-card--closed',
        complaint.follow_up_required && complaint.is_open ? 'complaint-card--follow-up' : '',
      ].join(' ')}
    >
      <div className="complaint-card__top">
        <div className="complaint-card__title">
          <strong className="list-card__title">{complaint.category}</strong>
          {showCallLink && (
            <span className="complaint-card__call">
              Call{' '}
              <Link
                className="text-link"
                to={`/post-call-analysis?call_id=${encodeURIComponent(complaint.call_id)}`}
              >
                {complaint.call_id}
              </Link>
            </span>
          )}
        </div>

        <div className="complaint-card__actions">
          {canAct && complaint.allowed_actions.length > 0 && pendingAction === null && (
            <div className="button-row complaint-card__buttons">
              {complaint.allowed_actions.map((action) => (
                <button
                  key={action}
                  type="button"
                  className={ACTIONS[action].primary ? 'button' : 'button button--secondary'}
                  disabled={isSaving}
                  onClick={() => {
                    setError(null)
                    setPendingAction(action)
                  }}
                >
                  {ACTIONS[action].label}
                </button>
              ))}
            </div>
          )}
          <div className="list-card__meta">
            {complaint.follow_up_required &&
              complaint.is_open &&
              complaint.status !== 'follow_up' && (
              <span className="badge badge--warning">Needs follow-up</span>
            )}
            <ComplaintStatusBadge status={complaint.status} />
          </div>
        </div>
      </div>

      <div className="complaint-card__progress">
        {!compact && <LifecycleTrack complaint={complaint} />}
        <div className="list-card__facts">
          <span>Detected: {formatRecordTimestamp(complaint.first_detected_at)}</span>
          <span>Last change: {formatRecordTimestamp(complaint.last_updated_at)}</span>
          {complaint.customer_id && <span>Customer: {complaint.customer_id}</span>}
        </div>
      </div>

      {lastNote && <p className="summary-delivery__message">{lastNote.note}</p>}

      {canAct && pendingAction !== null && (
        <div className="escalation-card__resolve">
          <label htmlFor={noteId}>{ACTIONS[pendingAction].prompt}</label>
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
              onClick={() => void submit(pendingAction)}
            >
              {isSaving ? 'Saving…' : ACTIONS[pendingAction].label}
            </button>
            <button
              type="button"
              className="button button--secondary"
              disabled={isSaving}
              onClick={() => setPendingAction(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {complaint.events.length > 0 && (
        <button
          type="button"
          className="text-link customer-panel__more"
          aria-expanded={showHistory}
          onClick={() => setShowHistory((current) => !current)}
        >
          {showHistory ? 'Hide history' : `Show history (${complaint.events.length})`}
        </button>
      )}
      {showHistory && <History events={complaint.events} />}

      {error && (
        <p className="review-form__error" role="alert">
          {error}
        </p>
      )}
    </article>
  )
}
