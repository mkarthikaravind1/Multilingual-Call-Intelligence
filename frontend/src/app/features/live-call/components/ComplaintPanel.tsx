import { ComplaintStatusBadge } from '../../../components/ToneBadges'

import type {
  ComplaintViewModel,
} from '../types/view-models'

type ComplaintPanelProps = {
  complaints: ComplaintViewModel[]
}

export function ComplaintPanel({
  complaints,
}: ComplaintPanelProps) {
  return (
    <section className="panel">
      <div className="live-call__section-heading">
        <div>
          <p className="panel__label">
            Complaint intelligence
          </p>

          <h4>
            Complaints recorded
          </h4>
        </div>

        <span className="live-call__count-badge">
          {complaints.length}
        </span>
      </div>

      {complaints.length === 0 ? (
        <div className="live-call__compact-empty">
          No complaints detected so far.
        </div>
      ) : (
        <div className="live-call__complaint-list">
          {complaints.map(
            (complaint) => (
              <div
                className="live-call__complaint-row"
                key={`${complaint.category}-${complaint.status}`}
              >
                <span>
                  {complaint.category}
                </span>

                <ComplaintStatusBadge status={complaint.status} />
              </div>
            ),
          )}
        </div>
      )}
    </section>
  )
}