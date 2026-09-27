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
          No complaint categories have
          been returned yet.
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

                <span className="live-call__status-tag">
                  {complaint.status}
                </span>
              </div>
            ),
          )}
        </div>
      )}
    </section>
  )
}