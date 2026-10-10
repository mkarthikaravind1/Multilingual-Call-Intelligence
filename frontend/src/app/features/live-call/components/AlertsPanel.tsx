import { humanizeLabel } from '../../../format/text'

import type { CallAlertViewModel } from '../types/view-models'

type AlertsPanelProps = {
  alerts: CallAlertViewModel[]
  // A finished call lists what was raised on it; a live one what stands now.
  isCallActive: boolean
}

// On-screen alerts beyond escalation: a complaint not asked about, a severe
// category, a detection the model was unsure of, poor audio.
export function AlertsPanel({ alerts, isCallActive }: AlertsPanelProps) {
  const standing = alerts.filter((alert) => alert.clearedAt === null)
  const shown = isCallActive ? standing : alerts
  if (shown.length === 0) {
    return null
  }

  return (
    <section className="panel call-alerts" aria-live="polite">
      <div className="live-call__section-heading">
        <div>
          <p className="panel__label">{isCallActive ? 'Needs attention' : 'Raised on this call'}</p>
          <h4>Alerts</h4>
        </div>
        <span className="live-call__count-badge">{shown.length}</span>
      </div>
      <ul className="call-alerts__list">
        {shown.map((alert) => (
          <li
            key={`${alert.alertType}-${alert.subject}`}
            className={`call-alerts__item call-alerts__item--${alert.alertType}${
              alert.clearedAt === null ? '' : ' call-alerts__item--cleared'
            }`}
          >
            <strong>{humanizeLabel(alert.alertType)}</strong>
            <span>{alert.message}</span>
            {!isCallActive && alert.clearedAt !== null && (
              <small>Cleared during the call</small>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
