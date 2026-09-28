import type { ReactNode } from 'react'

type StatePanelVariant = 'loading' | 'empty' | 'error' | 'pending'

type StatePanelProps = {
  variant?: StatePanelVariant
  title: string
  description?: ReactNode
  action?: ReactNode
  compact?: boolean
}

const ICONS: Record<Exclude<StatePanelVariant, 'loading'>, string> = {
  empty: '○',
  error: '!',
  pending: '…',
}

export function StatePanel({
  variant = 'empty',
  title,
  description,
  action,
  compact = false,
}: StatePanelProps) {
  const className = [
    'state-panel',
    `state-panel--${variant}`,
    compact ? 'state-panel--compact' : '',
  ].join(' ')

  return (
    <div
      className={className}
      role={variant === 'error' ? 'alert' : variant === 'loading' ? 'status' : undefined}
    >
      <span className="state-panel__icon" aria-hidden="true">
        {variant === 'loading' ? <span className="spinner" /> : ICONS[variant]}
      </span>

      <div className="state-panel__body">
        <strong>{title}</strong>
        {description && <p>{description}</p>}
        {action && <div className="state-panel__action">{action}</div>}
      </div>
    </div>
  )
}
