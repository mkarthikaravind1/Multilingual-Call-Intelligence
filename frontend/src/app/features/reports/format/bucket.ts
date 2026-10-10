import type { ReportBucket } from '../services/reportRestService'

export const dayFormat = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' })

// "5 Jan", or "Week of 5 Jan".
export function formatBucket(seconds: number, bucket: ReportBucket): string {
  const label = dayFormat.format(new Date(seconds * 1000))
  return bucket === 'week' ? `Week of ${label}` : label
}
