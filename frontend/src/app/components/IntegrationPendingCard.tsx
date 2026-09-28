type IntegrationPendingCardProps = {
  title: string
  description: string
}

// Shown where a backend capability is not connected yet. It deliberately
// renders no sample data.
export function IntegrationPendingCard({
  title,
  description,
}: IntegrationPendingCardProps) {
  return (
    <article className="integration-card">
      <div className="integration-card__header">
        <strong>{title}</strong>
        <span className="badge badge--pending">Integration pending</span>
      </div>
      <p>{description}</p>
    </article>
  )
}
