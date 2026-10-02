import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RecordTime } from '../../../components/RecordTime'

import { ApiError } from '../../../api/errors'
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

// What a person can mark a complaint as; saved with the card's Save button.
const DECISIONS: { value: ComplaintAction; label: string; prompt: string }[] = [
  { value: 'resolved', label: 'Resolved', prompt: 'How was it resolved? (optional)' },
  { value: 'unresolved', label: 'Unresolved', prompt: 'Why could it not be resolved? (optional)' },
]

// The in-call stages every complaint moves through, then its outcome.
const IN_CALL_STAGES: ComplaintStatus[] = ['detected', 'probed', 'covered']

export function ComplaintStatusBadge({ status }: { status: ComplaintStatus }) {
  return <span className={`badge ${STATUS_BADGES[status]}`}>{STATUS_LABELS[status]}</span>
}

// "Customer Name(Vehicle Number)", or as much of it as is known.
function customerLabel(complaint: ComplaintDto): string | null {
  if (!complaint.customer_name) return null
  return complaint.vehicle_registration
    ? `${complaint.customer_name}(${complaint.vehicle_registration})`
    : complaint.customer_name
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
              {actorLabel(event.actor)} · <RecordTime seconds={event.at} />
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
  // Cards listed away from their call (the queue, a customer's history) link
  // to the call's post-call analysis and name its customer.
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
  const current: ComplaintAction | null =
    complaint.status === 'resolved' || complaint.status === 'unresolved' ? complaint.status : null
  // The ticked choice, made for the status shown at the time; a newer status
  // (saved here, or by someone else and refreshed) starts over from it.
  const [choice, setChoice] = useState<{ forStatus: ComplaintStatus; value: ComplaintAction | null }>(
    { forStatus: complaint.status, value: current },
  )
  const selected = choice.forStatus === complaint.status ? choice.value : current
  const [note, setNote] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  const isDirty = selected !== null && selected !== current

  const choose = (value: ComplaintAction, checked: boolean) => {
    setError(null)
    // Ticking one unticks the other; unticking goes back to the saved status.
    setChoice({ forStatus: complaint.status, value: checked ? value : current })
  }

  const save = async () => {
    if (!isDirty || selected === null) return
    setIsSaving(true)
    setError(null)
    try {
      const updated = await complaintRestService.updateStatus(
        complaint.complaint_id,
        selected,
        note,
      )
      setNote('')
      onUpdated?.(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to update the complaint.')
    } finally {
      setIsSaving(false)
    }
  }

  // Only notes people wrote: the system's own note ("the call ended before
  // this complaint was resolved…") stays visible in the history.
  const lastNote = [...complaint.events]
    .reverse()
    .find((event) => event.note && event.actor !== 'system')
  const idBase = complaint.complaint_id.replace(/[^\w-]/g, '-')
  const customer = showCallLink ? customerLabel(complaint) : null
  const prompt = DECISIONS.find((d) => d.value === selected)?.prompt

  return (
    <article
      className={[
        'list-card',
        'complaint-card',
        complaint.is_open ? '' : 'complaint-card--closed',
      ].join(' ')}
    >
      <div className="complaint-card__top">
        <div className="complaint-card__title">
          <strong className="list-card__title">{complaint.category}</strong>
          {customer && <span className="complaint-card__customer">{customer}</span>}
          {showCallLink && (
            <Link
              className="text-link complaint-card__call"
              to={`/post-call-analysis?call_id=${encodeURIComponent(complaint.call_id)}`}
              title={`Call ${complaint.call_id}`}
            >
              Post Call Analysis
            </Link>
          )}
        </div>

        <div className="complaint-card__actions">
          {canAct && (
            <div className="complaint-card__decision">
              <fieldset className="complaint-card__choices" aria-label="Mark complaint as">
                {DECISIONS.map((decision) => (
                  <label key={decision.value} className="complaint-card__choice">
                    <input
                      type="checkbox"
                      checked={selected === decision.value}
                      disabled={
                        isSaving ||
                        decision.value === current ||
                        !complaint.allowed_actions.includes(decision.value)
                      }
                      onChange={(event) => choose(decision.value, event.target.checked)}
                    />
                    {decision.label}
                  </label>
                ))}
              </fieldset>
              <button
                type="button"
                className="button"
                disabled={!isDirty || isSaving}
                onClick={() => void save()}
              >
                {isSaving ? 'Saving…' : 'Save'}
              </button>
            </div>
          )}
          {/* Only the outcome is badged; in-call stages show on the track. */}
          {current && (
            <div className="list-card__meta">
              <ComplaintStatusBadge status={current} />
            </div>
          )}
        </div>
      </div>

      <div className="complaint-card__progress">
        {!compact && <LifecycleTrack complaint={complaint} />}
        <div className="list-card__facts">
          <span>Detected: <RecordTime seconds={complaint.first_detected_at} /></span>
          <span>Last change: <RecordTime seconds={complaint.last_updated_at} /></span>
        </div>
      </div>

      {lastNote && <p className="summary-delivery__message">{lastNote.note}</p>}

      {canAct && isDirty && (
        <div className="escalation-card__resolve">
          <label htmlFor={`complaint-note-${idBase}`}>{prompt}</label>
          <textarea
            id={`complaint-note-${idBase}`}
            rows={2}
            maxLength={500}
            value={note}
            disabled={isSaving}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
      )}

      {complaint.events.length > 0 && (
        <button
          type="button"
          className="text-link customer-panel__more"
          aria-expanded={showHistory}
          onClick={() => setShowHistory((shown) => !shown)}
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
