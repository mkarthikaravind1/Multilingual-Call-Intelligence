export function DashboardPage() {
  return (
    <section className="page-shell">
      <div className="page-shell__header">
        <div>
          <p className="eyebrow">Operations</p>
          <h2>Customer intelligence overview</h2>
        </div>
      </div>

      <div className="page-shell__grid">
        <article className="panel panel--highlight">
          <p className="panel__label">Today’s response rate</p>
          <h3>87.4%</h3>
          <span>Across active dealership conversations</span>
        </article>
        <article className="panel">
          <p className="panel__label">Live calls</p>
          <h3>12</h3>
          <span>Currently monitored</span>
        </article>
        <article className="panel">
          <p className="panel__label">Pending review</p>
          <h3>9</h3>
          <span>Cases awaiting escalation outcome</span>
        </article>
      </div>
    </section>
  )
}
