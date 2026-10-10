import { useEffect, useState } from 'react'

import { reportRestService, type CallAuditDto } from '../services/reportRestService'

type CallAuditPanelProps = {
  callId: string
  // Changes when the call's record changes (it ended, its summary arrived),
  // so the audit is read again.
  refreshToken?: string
}

// How the audit is scored; keep in step with the backend's rules
// (app/services/quality_audit.py).
const RULES = [
  'Each complaint: 60 points when the executive asked about it, 20 when they accepted a question suggested about it (counted only when one was suggested), 20 once it has been resolved. Its score is the points earned out of those that apply.',
  'The call: the average of its complaints’ scores, plus 5 when the customer ended in a milder tone than they began, minus 10 when harsher, minus 10 for a high or critical escalation left open, minus 5 for more than 2 minutes on hold. Kept between 0 and 100.',
  'A call with no complaint starts from 100.',
]

const signed = (points: number) => (points > 0 ? `+${points}` : String(points))

// The call's quality audit: a score by fixed rules, with a score per
// complaint category and the reason for each point. For supervisors.
export function CallAuditPanel({ callId, refreshToken = '' }: CallAuditPanelProps) {
  const [loaded, setLoaded] = useState<{ key: string; audit: CallAuditDto | null } | null>(null)
  const key = `${callId}|${refreshToken}`

  useEffect(() => {
    let cancelled = false
    reportRestService
      .getCallAudit(callId)
      .then((audit) => {
        if (!cancelled) setLoaded({ key, audit })
      })
      .catch(() => {
        // The rest of the call's page works without it.
        if (!cancelled) setLoaded({ key, audit: null })
      })
    return () => {
      cancelled = true
    }
  }, [callId, key])

  const audit = loaded?.audit
  if (!audit) return null

  return (
    <section className="panel call-audit">
      <div className="section-heading">
        <div>
          <p className="panel__label">Quality audit</p>
          <h3 className="section-title">
            Audit score <em className="report-estimate">estimate</em>
          </h3>
        </div>
        <strong className="call-audit__score">
          {audit.score.toFixed(0)}
          <span> / 100</span>
        </strong>
      </div>

      {audit.categories.length === 0 ? (
        <p className="customer-panel__muted">
          No complaint was raised on this call, so there is no category to score.
        </p>
      ) : (
        <ul className="call-audit__categories">
          {audit.categories.map((category) => (
            <li key={category.category}>
              <div className="call-audit__category">
                <strong>{category.category}</strong>
                {category.unsure && (
                  <span
                    className="badge badge--neutral"
                    title="The AI was not sure this complaint was raised"
                  >
                    Detected with low confidence
                  </span>
                )}
                <span className="call-audit__category-score">{category.score.toFixed(0)} / 100</span>
              </div>
              <ul className="call-audit__points">
                {category.points.map((point) => (
                  <li
                    key={point.rule}
                    className={point.points > 0 ? 'call-audit__point--earned' : undefined}
                  >
                    <span>
                      {point.points} of {point.possible}
                    </span>
                    {point.note}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      {audit.adjustments.length > 0 && (
        <ul className="call-audit__points call-audit__points--call">
          {audit.adjustments.map((point) => (
            <li
              key={point.rule}
              className={point.points > 0 ? 'call-audit__point--earned' : undefined}
            >
              <span>{signed(point.points)}</span>
              {point.note}
            </li>
          ))}
        </ul>
      )}

      <details className="report-table-toggle">
        <summary>How this score is worked out</summary>
        <ul className="call-audit__rules">
          {RULES.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
      </details>
    </section>
  )
}
