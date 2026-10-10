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
  // The customer's own words on one of the calls; null when not known.
  quote?: string | null
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

// One day or week of a tone trend.
export interface TonePointDto {
  // Calls with a tone, and those ending negative or worse.
  rated: number
  negative: number
}

export interface ToneSummaryDto {
  rated_calls: number
  // By the tone the call ended on, mildest first.
  by_tone: Array<{ label: ReportSentiment; calls: number }>
  negative_calls: number
  // Calls whose lines carry tones, and those whose customer ended in a
  // milder, or a harsher, tone than they began.
  tracked_calls: number
  improved_calls: number
  worsened_calls: number
  // One per bucket_starts entry.
  trend: TonePointDto[]
}

export interface AuditPointDto {
  rule: string
  points: number
  // The most the rule could have earned; 0 for a call-level adjustment.
  possible: number
  note: string
}

// A call's quality audit: an estimate by fixed rules.
export interface CallAuditDto {
  call_id: string
  // 0 to 100.
  score: number
  categories: Array<{
    category: string
    score: number
    points: AuditPointDto[]
    // The AI was not sure this complaint was raised at all.
    unsure: boolean
  }>
  adjustments: AuditPointDto[]
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
  // How the calls ended, and the tone per day or week.
  tone: ToneSummaryDto
}

// Estimates worked out by fixed rules (see the Performance view). Rates
// are 0 to 1, and null when there is nothing to work them out from.
export interface FiguresDto {
  calls: number
  complaints: number
  probed_complaints: number
  coverage_score: number | null
  fcr_calls: number
  fcr_resolved: number
  fcr_rate: number | null
  known_customer_complaints: number
  repeat_complaints: number
  repeat_rate: number | null
  churn_low: number
  churn_medium: number
  churn_high: number
  rated_calls: number
  negative_calls: number
  // 1 to 5.
  csat: number | null
  serious_escalations: number
  // Suggested questions the executive accepted, and skipped.
  questions_accepted: number
  questions_skipped: number
  // Quality audit: calls that raised a complaint, their average score (0
  // to 100), and the category handled worst on average with its score.
  audited_calls: number
  audit_score: number | null
  weakest_category: string | null
  weakest_category_score: number | null
}

export interface PerformanceReportDto {
  overall: FiguresDto
  // Most calls first; executive_user_id null: calls with no executive recorded.
  executives: Array<{
    executive_user_id: string | null
    name: string
    figures: FiguresDto
    // Their calls' tone per day or week (one per bucket_starts entry).
    tone_trend: TonePointDto[]
  }>
  bucket: ReportBucket
  // When each day or week of the tone trends starts (epoch seconds).
  bucket_starts: number[]
  tone_trend: TonePointDto[]
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

  getPerformanceReport(filters: ReportFilters): Promise<PerformanceReportDto> {
    return apiClient.get<PerformanceReportDto>(
      `/api/v1/reports/performance?${toQuery(filters).toString()}`,
    )
  },

  getCallAudit(callId: string): Promise<CallAuditDto> {
    return apiClient.get<CallAuditDto>(
      `/api/v1/reports/calls/${encodeURIComponent(callId)}/audit`,
    )
  },

  exportScorecard(filters: ReportFilters, format: 'csv' | 'xlsx'): Promise<Blob> {
    const query = toQuery(filters)
    query.set('format', format)
    return apiClient.download(`/api/v1/reports/performance/export?${query.toString()}`)
  },

  // The same report as a file.
  exportComplaintReport(filters: ReportFilters, format: ReportExportFormat): Promise<Blob> {
    const query = toQuery(filters)
    query.set('format', format)
    return apiClient.download(`${basePath}/export?${query.toString()}`)
  },
}
