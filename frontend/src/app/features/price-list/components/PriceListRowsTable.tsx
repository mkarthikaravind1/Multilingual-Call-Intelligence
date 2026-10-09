import type { PriceListIssueDto, PriceListRowDto } from '../types/dto'

type PriceListRowsTableProps = {
  rows: PriceListRowDto[]
  // The number shown for each row (spreadsheet row for an upload, list
  // position otherwise); issues refer to these numbers.
  rowNumbers: number[]
  // Indexes into rows of the rows to show.
  visible: number[]
  issues?: PriceListIssueDto[]
  onEdit?: (index: number) => void
  onDelete?: (index: number) => void
}

const cell = (value: string | number | null | undefined) =>
  value === null || value === undefined || value === '' ? '—' : value

export function PriceListRowsTable({
  rows,
  rowNumbers,
  visible,
  issues = [],
  onEdit,
  onDelete,
}: PriceListRowsTableProps) {
  const rowsWithErrors = new Set(
    issues.filter((issue) => issue.severity === 'error').map((issue) => issue.row),
  )
  const hasActions = Boolean(onEdit || onDelete)

  return (
    <div className="price-list__table-wrap">
      <table className="price-list__table">
        <thead>
          <tr>
            <th>#</th>
            <th>Vehicle model</th>
            <th>Service</th>
            <th>Part</th>
            <th>Qty</th>
            <th>Unit price</th>
            <th>GST %</th>
            <th>Labour h</th>
            <th>Duration h</th>
            <th>Keywords</th>
            <th>Includes</th>
            {hasActions && <th aria-label="Actions" />}
          </tr>
        </thead>
        <tbody>
          {visible.map((index) => {
            const row = rows[index]
            const number = rowNumbers[index]
            return (
              <tr
                key={`${number}-${index}`}
                className={rowsWithErrors.has(number) ? 'price-list__row--error' : undefined}
              >
                <td>{number}</td>
                <td>{row.vehicle_model ?? 'All models'}</td>
                <td>{cell(row.service)}</td>
                <td>{cell(row.part)}</td>
                <td>{cell(row.part ? (row.quantity ?? 1) : null)}</td>
                <td>{cell(row.unit_price)}</td>
                <td>{row.part ? (row.gst_percent ?? 'default') : '—'}</td>
                <td>{cell(row.labour_hours)}</td>
                <td>{cell(row.duration_hours)}</td>
                <td>{cell(row.keywords.join(', '))}</td>
                <td>{cell(row.includes.join(', '))}</td>
                {hasActions && (
                  <td className="price-list__actions">
                    {onEdit && (
                      <button
                        type="button"
                        className="button button--secondary"
                        onClick={() => onEdit(index)}
                      >
                        Edit
                      </button>
                    )}
                    {onDelete && (
                      <button
                        type="button"
                        className="button button--danger"
                        onClick={() => onDelete(index)}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
