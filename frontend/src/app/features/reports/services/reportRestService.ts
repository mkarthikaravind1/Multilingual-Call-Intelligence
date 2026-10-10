import { apiClient } from '../../../api/client'
import type { CallDirection } from '../../live-call/types/dto'

export type ReportBucket = 'day' | 'week'
export type ReportSentiment = 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | 'FRUSTRATED' | 'ESCALATING'
export type ReportExportFormat = 'csv' | 'xlsx' | 'pdf'

// Calls started in [startedFrom, startedTo) (epoch seconds); the rest are
// optional and must all match.
export interface ReportFilters {
  startedFrom: number
  startedTo: number
  locationId?: string
  executiveUserId?: string
  direction?: CallDirection
  sentiment?: ReportSentiment
  category?: string
  // Left out: by day for a short range, by week for a long one.
  bucket?: ReportBucket
}

export interface CategoryTotalDto {
  category: string
  complaints: number
  // Of those, resolved by now.
  resolved: number
}

export interface ThemeDto {
  // The first of the similar descriptions.
  text: string
  complaints: number
  call_ids: string[]
}

export interface RootCauseDto {
  category: string
  complaints: number
  resolved: number
  // Complaints no call summary describes.
  undescribed: number
  themes: ThemeDto[]
}

export interface ComplaintReportDto {
  bucket: ReportBucket
  total_calls: number
  calls_with_complaints: number
  total_complaints: number
  // Most frequent first; the per-category lists below are in this order.
  categories: CategoryTotalDto[]
  // When each day or week starts (epoch seconds); one per trend count.
  bucket_starts: number[]
  trend: Array<{ category: string; counts: number[] }>
  // One per heatmap count; location_id null: calls without a location.
  locations: Array<{ location_id: string | null; name: string }>
  heatmap: Array<{ category: string; counts: number[] }>
  root_causes: RootCauseDto[]
}

function toQuery(filters: ReportFilters): URLSearchParams {
  const query = new URLSearchParams({
    started_from: String(filters.startedFrom),
    started_to: String(filters.startedTo),
    // So that days and weeks start at this browser's midnight.
    tz_offset_minutes: String(-new Date().getTimezoneOffset()),
  })
  const optional: Array<[string, string | undefined]> = [
    ['location_id', filters.locationId],
    ['executive_user_id', filters.executiveUserId],
    ['direction', filters.direction],
    ['sentiment', filters.sentiment],
    ['category', filters.category],
    ['bucket', filters.bucket],
  ]
  for (const [name, value] of optional) {
    if (value) query.set(name, value)
  }
  return query
}

const basePath = '/api/v1/reports/complaints'

export const reportRestService = {
  getComplaintReport(filters: ReportFilters): Promise<ComplaintReportDto> {
    return apiClient.get<ComplaintReportDto>(`${basePath}?${toQuery(filters).toString()}`)
  },

  // The same report as a file.
  exportComplaintReport(filters: ReportFilters, format: ReportExportFormat): Promise<Blob> {
    const query = toQuery(filters)
    query.set('format', format)
    return apiClient.download(`${basePath}/export?${query.toString()}`)
  },
}
