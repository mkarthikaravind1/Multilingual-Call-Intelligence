export function CallHistoryPage() {
  return (
    <section className="page-shell">
      <div className="page-shell__header">
        <div>
          <p className="eyebrow">Records</p>
          <h2>Call history</h2>
        </div>
      </div>

      <div className="panel panel--list">
        <div className="table-row table-row--head">
          <span>Customer</span>
          <span>Dealer</span>
          <span>Outcome</span>
          <span>Time</span>
        </div>
        <div className="table-row">
          <span>Priya Nair</span>
          <span>Northside Auto</span>
          <span>Resolved</span>
          <span>08:40 AM</span>
        </div>
        <div className="table-row">
          <span>Javier Mendez</span>
          <span>Metro Motors</span>
          <span>Escalated</span>
          <span>09:55 AM</span>
        </div>
      </div>
    </section>
  )
}
