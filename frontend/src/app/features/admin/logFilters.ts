// <input type="date"> values are local calendar days ("2026-10-02"); the API
// takes epoch seconds, from inclusive and to exclusive.
export function localMidnight(day: string, addDays = 0): number | undefined {
  const [year, month, date] = day.split('-').map(Number)
  if (!year || !month || !date) return undefined
  return new Date(year, month - 1, date + addDays).getTime() / 1000
}

export const LOG_PAGE_SIZE = 50

// A copy of the address's filters with these changed (null or '' removes
// one). Any change goes back to the first page.
export function withFilter(
  current: URLSearchParams,
  changes: Record<string, string | null>,
  offsetParam = 'offset',
): URLSearchParams {
  const next = new URLSearchParams(current)
  for (const [name, value] of Object.entries(changes)) {
    if (value) next.set(name, value)
    else next.delete(name)
  }
  if (!(offsetParam in changes)) next.delete(offsetParam)
  return next
}
