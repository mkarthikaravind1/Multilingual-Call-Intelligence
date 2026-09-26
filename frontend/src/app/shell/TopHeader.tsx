type TopHeaderProps = {
  title: string
  subtitle?: string
}

export function TopHeader({ title, subtitle }: TopHeaderProps) {
  return (
    <header className="top-header">
      <div className="top-header__copy">
        <h1 className="top-header__title">{title}</h1>
        {subtitle ? <p className="top-header__subtitle">{subtitle}</p> : null}
      </div>

      <div className="top-header__actions" aria-label="Session controls">
        <div className="top-header__pill">Connected</div>
        <div className="top-header__avatar" aria-label="User profile">
          U
        </div>
      </div>
    </header>
  )
}
