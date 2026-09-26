export function PostCallAnalysisPage() {
  return (
    <section className="page-shell">
      <div className="page-shell__header">
        <div>
          <p className="eyebrow">Review</p>
          <h2>Post-call analysis</h2>
        </div>
      </div>

      <div className="page-shell__grid">
        <article className="panel">
          <p className="panel__label">Sentiment</p>
          <h3>Positive</h3>
          <span>Customer confidence increased by 14%</span>
        </article>
        <article className="panel">
          <p className="panel__label">Detected issues</p>
          <h3>2</h3>
          <span>Low inventory and service delay</span>
        </article>
      </div>
    </section>
  )
}
