import type { PriceListIssueDto } from '../types/dto'

type PriceListIssuesProps = {
  issues: PriceListIssueDto[]
  // "Row" for list positions, "Sheet row" for an uploaded file.
  rowLabel?: string
}

const MAX_SHOWN = 50

export function PriceListIssues({ issues, rowLabel = 'Row' }: PriceListIssuesProps) {
  if (issues.length === 0) {
    return null
  }
  const errors = issues.filter((issue) => issue.severity === 'error')
  const warnings = issues.filter((issue) => issue.severity === 'warning')

  const list = (items: PriceListIssueDto[], className: string) => (
    <ul className={`price-list__issues ${className}`}>
      {items.slice(0, MAX_SHOWN).map((issue, index) => (
        <li key={index}>
          {issue.row !== null && <strong>{rowLabel} {issue.row}: </strong>}
          {issue.message}
        </li>
      ))}
      {items.length > MAX_SHOWN && <li>…and {items.length - MAX_SHOWN} more.</li>}
    </ul>
  )

  return (
    <div className="price-list__issue-block">
      {errors.length > 0 && (
        <div role="alert">
          <p className="review-form__error">
            {errors.length} problem{errors.length === 1 ? '' : 's'} to fix before saving:
          </p>
          {list(errors, 'price-list__issues--error')}
        </div>
      )}
      {warnings.length > 0 && (
        <div>
          <p className="customer-panel__muted">
            {warnings.length} warning{warnings.length === 1 ? '' : 's'} (saving is still allowed):
          </p>
          {list(warnings, 'price-list__issues--warning')}
        </div>
      )}
    </div>
  )
}
