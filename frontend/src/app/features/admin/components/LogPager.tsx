import { LOG_PAGE_SIZE } from '../logFilters'

interface LogPagerProps {
  offset: number
  shown: number
  total: number
  // What is counted: "entries", "requests".
  noun: string
  onOffset: (offset: number) => void
}

export function LogPager({ offset, shown, total, noun, onOffset }: LogPagerProps) {
  return (
    <div className="pager">
      <span>
        Showing <strong>{offset + 1}–{offset + shown}</strong> of <strong>{total}</strong> {noun},
        newest first
      </span>
      {total > LOG_PAGE_SIZE && (
        <div className="button-row">
          <button
            type="button"
            className="button button--secondary"
            onClick={() => onOffset(Math.max(0, offset - LOG_PAGE_SIZE))}
            disabled={offset === 0}
          >
            Previous
          </button>
          <button
            type="button"
            className="button button--secondary"
            onClick={() => onOffset(offset + LOG_PAGE_SIZE)}
            disabled={offset + shown >= total}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
