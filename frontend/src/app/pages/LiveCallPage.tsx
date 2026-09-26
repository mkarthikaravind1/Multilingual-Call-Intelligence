export function LiveCallPage() {
  return (
    <section className="page-shell">
      <div className="page-shell__header">
        <div>
          <p className="eyebrow">Live</p>
          <h2>Call workspace</h2>
        </div>
      </div>

      <div className="page-shell__grid page-shell__grid--wide">
        <article className="panel panel--wide">
          <p className="panel__label">Active conversation</p>
          <h3>Vehicle service follow-up</h3>
          <p className="panel__text">This area provides a live contact monitoring surface for future transcription, insights, and agent actions.</p>
        </article>
        <article className="panel">
          <p className="panel__label">Customer context</p>
          <ul className="info-list">
            <li>VIN: 1HGBH41JXMN109186</li>
            <li>Last visit: 12 April</li>
            <li>Preferred channel: Phone</li>
          </ul>
        </article>
      </div>
    </section>
  )
}
