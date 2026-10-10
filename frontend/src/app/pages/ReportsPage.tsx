import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiError } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { complaintRestService } from '../features/complaints/services/complaintRestService'
import { useCallDirectory } from '../features/live-call/hooks/useCallDirectory'
import { TrendChart, type TrendLine } from '../features/reports/components/TrendChart'
import { formatBucket } from '../features/reports/format/bucket'
import {
  reportRestService,
  type ComplaintReportDto,
  type ReportBucket,
  type ReportExportFormat,
  type ReportFilters,
  type ReportSentiment,
} from '../features/reports/services/reportRestService'

// Filters live in the URL, so a report can be bookmarked or sent to someone.
const PARAM = {
  from: 'from',
  to: 'to',
  location: 'location',
  executive: 'executive',
  category: 'category',
  sentiment: 'tone',
  direction: 'direction',
  bucket: 'by',
} as const

const DEFAULT_RANGE_DAYS = 30
const SENTIMENTS: Array<{ id: ReportSentiment; name: string }> = [
  { id: 'POSITIVE', name: 'Positive' },
  { id: 'NEUTRAL', name: 'Neutral' },
  { id: 'NEGATIVE', name: 'Negative' },
  { id: 'FRUSTRATED', name: 'Frustrated' },
  { id: 'ESCALATING', name: 'Escalating' },
]
const DIRECTIONS = [
  { id: 'inbound', name: 'Incoming' },
  { id: 'outbound', name: 'Outgoing' },
] as const
const BUCKETS: Array<{ id: ReportBucket; name: string }> = [
  { id: 'day', name: 'Day' },
  { id: 'week', name: 'Week' },
]
const EXPORTS: Array<{ format: ReportExportFormat; label: string }> = [
  { format: 'xlsx', label: 'Excel' },
  { format: 'csv', label: 'CSV' },
  { format: 'pdf', label: 'PDF' },
]

// The trend draws this many categories; the rest are added up as "Other".
const MAX_TREND_LINES = 5
const SERIES_COLORS = [1, 2, 3, 4, 5].map((slot) => `var(--chart-series-${slot})`)
const OTHER_COLOR = 'var(--chart-series-other)'
// Light to dark: more complaints, darker cell.
const HEAT_STEPS = 6

// "2026-10-02" for a local calendar day, as <input type="date"> uses.
function dayValue(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function localMidnight(day: string, addDays = 0): number | undefined {
  const [year, month, date] = day.split('-').map(Number)
  if (!year || !month || !date) return undefined
  return new Date(year, month - 1, date + addDays).getTime() / 1000
}

function defaultRange(): { from: string; to: string } {
  const today = new Date()
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (DEFAULT_RANGE_DAYS - 1))
  return { from: dayValue(start), to: dayValue(today) }
}

function saveFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

// Each category keeps its colour while it is drawn: by its place in the
// category list, not by how often it comes up under the current filters.
function trendLines(report: ComplaintReportDto, categoryOrder: string[]): TrendLine[] {
  const shown = report.trend.slice(0, MAX_TREND_LINES)
  const rest = report.trend.slice(MAX_TREND_LINES)
  const taken = new Set<number>()
  const slotOf = new Map<string, number>()
  const byListOrder = [...shown].sort(
    (a, b) => categoryOrder.indexOf(a.category) - categoryOrder.indexOf(b.category),
  )
  for (const series of byListOrder) {
    const place = Math.max(0, categoryOrder.indexOf(series.category))
    let slot = place % SERIES_COLORS.length
    while (taken.has(slot)) slot = (slot + 1) % SERIES_COLORS.length
    taken.add(slot)
    slotOf.set(series.category, slot)
  }
  const lines: TrendLine[] = shown.map((series) => ({
    ...series,
    color: SERIES_COLORS[slotOf.get(series.category) ?? 0],
  }))
  if (rest.length > 0) {
    lines.push({
      category: `Other (${rest.length} categories)`,
      counts: report.bucket_starts.map((_, index) =>
        rest.reduce((sum, series) => sum + series.counts[index], 0),
      ),
      color: OTHER_COLOR,
    })
  }
  return lines
}

type Loaded = { key: string; report: ComplaintReportDto | null; error: string | null }

export function ReportsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const directory = useCallDirectory()
  const [categories, setCategories] = useState<string[]>([])
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [exporting, setExporting] = useState<ReportExportFormat | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    complaintRestService
      .listCategories()
      .then((list) => {
        if (!cancelled) setCategories(list.map((category) => category.name))
      })
      .catch(() => {
        // The filter then offers only the categories in the report.
      })
    return () => {
      cancelled = true
    }
  }, [])

  // The last 30 days, fixed when the page opens.
  const [range] = useState(defaultRange)
  const from = searchParams.get(PARAM.from) ?? range.from
  const to = searchParams.get(PARAM.to) ?? range.to
  const startedFrom = localMidnight(from)
  const startedTo = localMidnight(to, 1)
  const rangeError =
    startedFrom === undefined || startedTo === undefined
      ? 'Choose both dates.'
      : startedFrom >= startedTo
        ? '“From” is after “To”.'
        : null

  const value = (name: string) => searchParams.get(name) ?? ''
  const filters: ReportFilters | null = rangeError
    ? null
    : {
        startedFrom: startedFrom!,
        startedTo: startedTo!,
        locationId: value(PARAM.location) || undefined,
        executiveUserId: value(PARAM.executive) || undefined,
        category: value(PARAM.category) || undefined,
        sentiment: SENTIMENTS.find((s) => s.id === value(PARAM.sentiment))?.id,
        direction: DIRECTIONS.find((d) => d.id === value(PARAM.direction))?.id,
        bucket: BUCKETS.find((b) => b.id === value(PARAM.bucket))?.id,
      }
  const filterKey = filters ? JSON.stringify(filters) : ''

  useEffect(() => {
    if (!filterKey) return
    let cancelled = false
    reportRestService
      .getComplaintReport(JSON.parse(filterKey) as ReportFilters)
      .then((report) => {
        if (!cancelled) setLoaded({ key: filterKey, report, error: null })
      })
      .catch((err) => {
        if (cancelled) return
        setLoaded({
          key: filterKey,
          report: null,
          error: err instanceof ApiError ? err.message : 'Unable to load the report.',
        })
      })
    return () => {
      cancelled = true
    }
  }, [filterKey])

  const setParam = (name: string, next: string) => {
    const params = new URLSearchParams(window.location.search)
    if (next) params.set(name, next)
    else params.delete(name)
    setSearchParams(params, { replace: true })
  }

  const download = async (format: ReportExportFormat) => {
    if (!filters) return
    setExporting(format)
    setExportError(null)
    try {
      const blob = await reportRestService.exportComplaintReport(filters, format)
      saveFile(blob, `complaint-report-${from}-to-${to}.${format}`)
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Unable to download the report.')
    } finally {
      setExporting(null)
    }
  }

  const choice = (
    name: string,
    label: string,
    options: ReadonlyArray<{ id: string; name: string; is_active?: boolean }>,
    all = 'All',
  ) => (
    <label className="call-filters__choice">
      <span>{label}</span>
      <select value={value(name)} onChange={(event) => setParam(name, event.target.value)}>
        <option value="">{all}</option>
        {options
          .filter((option) => option.is_active !== false || option.id === value(name))
          .map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
      </select>
    </label>
  )

  const isLoading = Boolean(filterKey) && loaded?.key !== filterKey
  const report = loaded?.report ?? null
  // The category list, plus any category in the report that has left it.
  const categoryOptions = useMemo(() => {
    const names = [...categories]
    for (const total of report?.categories ?? []) {
      if (!names.includes(total.category)) names.push(total.category)
    }
    const chosen = searchParams.get(PARAM.category)
    if (chosen && !names.includes(chosen)) names.push(chosen)
    return names
  }, [categories, report, searchParams])

  const lines = useMemo(
    () => (report ? trendLines(report, categoryOptions) : []),
    [report, categoryOptions],
  )
  const heatMax = Math.max(1, ...(report?.heatmap ?? []).flatMap((row) => row.counts))
  const mostComplaints = Math.max(1, ...(report?.categories ?? []).map((c) => c.complaints))

  return (
    <section className="page-shell reports-page">
      <div className="panel call-filters" role="search" aria-label="Report filters">
        <div className="call-filters__row">
          <fieldset className="call-filters__range">
            <legend>Call date</legend>
            <label className="call-filters__date">
              <span>From</span>
              <input
                type="date"
                value={from}
                max={to}
                onChange={(event) => setParam(PARAM.from, event.target.value)}
              />
            </label>
            <label className="call-filters__date">
              <span>To</span>
              <input
                type="date"
                value={to}
                min={from}
                onChange={(event) => setParam(PARAM.to, event.target.value)}
              />
            </label>
            {rangeError && (
              <span className="call-filters__hint" role="alert">
                {rangeError}
              </span>
            )}
          </fieldset>
          {choice(PARAM.location, 'Location', directory.locations)}
          {choice(PARAM.executive, 'Executive', directory.executives)}
          {choice(
            PARAM.category,
            'Category',
            categoryOptions.map((name) => ({ id: name, name })),
          )}
          {choice(PARAM.sentiment, 'Tone', SENTIMENTS)}
          {choice(PARAM.direction, 'Direction', DIRECTIONS)}
          {choice(PARAM.bucket, 'Trend by', BUCKETS, 'Automatic')}
        </div>
        <div className="call-filters__row">
          <div className="call-filters__actions">
            {isLoading && loaded && (
              <span className="call-filters__status" role="status">
                <span className="spinner" aria-hidden="true" /> Updating…
              </span>
            )}
            <span className="customer-panel__muted">Download what these filters show:</span>
            {EXPORTS.map(({ format, label }) => (
              <button
                key={format}
                type="button"
                className="button button--secondary"
                disabled={!filters || exporting !== null}
                onClick={() => void download(format)}
              >
                {exporting === format ? 'Preparing…' : label}
              </button>
            ))}
            <button
              type="button"
              className="button button--secondary"
              disabled={[...searchParams.keys()].length === 0}
              onClick={() => setSearchParams(new URLSearchParams(), { replace: true })}
            >
              Clear filters
            </button>
          </div>
        </div>
        {exportError && (
          <p className="review-form__error" role="alert">
            {exportError}
          </p>
        )}
      </div>

      {!loaded && !rangeError && <StatePanel variant="loading" title="Loading the report…" compact />}
      {loaded?.error && (
        <StatePanel variant="error" title="Could not load the report" description={loaded.error} />
      )}

      {report && (
        <>
          <div className="report-tiles">
            <div className="report-tile">
              <span>Calls</span>
              <strong>{report.total_calls}</strong>
            </div>
            <div className="report-tile">
              <span>Calls with a complaint</span>
              <strong>{report.calls_with_complaints}</strong>
            </div>
            <div className="report-tile">
              <span>Complaints</span>
              <strong>{report.total_complaints}</strong>
            </div>
          </div>

          {report.total_complaints === 0 ? (
            <StatePanel
              title="No complaints match these filters"
              description="Try a wider date range or fewer filters."
              compact
            />
          ) : (
            <>
              <section className="panel">
                <h3 className="section-title">Complaints by category</h3>
                <div className="report-bars">
                  {report.categories.map((total) => (
                    <div className="report-bars__row" key={total.category}>
                      <span className="report-bars__label">{total.category}</span>
                      <span className="report-bars__track">
                        <span
                          className="report-bars__bar"
                          style={{ width: `${(total.complaints / mostComplaints) * 100}%` }}
                          title={`${total.category}: ${total.complaints} complaints, ${total.resolved} resolved`}
                        />
                      </span>
                      <span className="report-bars__value">
                        <strong>{total.complaints}</strong>
                        <small>{total.resolved} resolved</small>
                      </span>
                    </div>
                  ))}
                </div>
              </section>

              <section className="panel">
                <div className="section-heading">
                  <h3 className="section-title">Category trend</h3>
                  <span className="customer-panel__muted">
                    Complaints per {report.bucket}
                  </span>
                </div>
                <TrendChart
                  bucket={report.bucket}
                  bucketStarts={report.bucket_starts}
                  lines={lines}
                />
                <details className="report-table-toggle">
                  <summary>Show the numbers as a table</summary>
                  <div className="report-table-scroll">
                    <table className="report-table">
                      <thead>
                        <tr>
                          <th scope="col">Category</th>
                          {report.bucket_starts.map((start) => (
                            <th scope="col" key={start}>
                              {formatBucket(start, report.bucket).replace('Week of ', '')}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {report.trend.map((series) => (
                          <tr key={series.category}>
                            <th scope="row">{series.category}</th>
                            {series.counts.map((count, index) => (
                              <td key={report.bucket_starts[index]}>{count}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </section>

              <section className="panel">
                <div className="section-heading">
                  <h3 className="section-title">Category by location</h3>
                  <span className="customer-panel__muted">Darker: more complaints</span>
                </div>
                <div className="report-table-scroll">
                  <table className="report-table report-heatmap">
                    <thead>
                      <tr>
                        <th scope="col">Category</th>
                        {report.locations.map((location) => (
                          <th scope="col" key={location.location_id ?? 'none'}>
                            {location.name}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {report.heatmap.map((row) => (
                        <tr key={row.category}>
                          <th scope="row">{row.category}</th>
                          {row.counts.map((count, index) => {
                            const step =
                              count === 0 ? 0 : Math.max(1, Math.ceil((count / heatMax) * HEAT_STEPS))
                            const location = report.locations[index]
                            return (
                              <td
                                key={location.location_id ?? 'none'}
                                className={`report-heatmap__cell report-heatmap__cell--${step}`}
                                title={`${row.category} · ${location.name}: ${count} complaints`}
                              >
                                {count}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="panel">
                <div className="section-heading">
                  <h3 className="section-title">Root causes</h3>
                  <span className="customer-panel__muted">
                    Complaints described in similar words, grouped by a fixed rule (no AI)
                  </span>
                </div>
                <div className="card-stack">
                  {report.root_causes.map((cause) => (
                    <article className="list-card" key={cause.category}>
                      <div className="section-heading complaint-card__heading">
                        <strong className="list-card__title">{cause.category}</strong>
                        <div className="list-card__meta">
                          <span className="badge">{cause.complaints} complaints</span>
                          <span className="badge">{cause.resolved} resolved</span>
                        </div>
                      </div>
                      {cause.themes.length > 0 && (
                        <ul className="report-themes">
                          {cause.themes.map((theme) => (
                            <li key={theme.text}>
                              <span className="report-themes__count">{theme.complaints}×</span>
                              <span>
                                {theme.text}
                                <span className="report-themes__calls">
                                  {theme.call_ids.map((callId, index) => (
                                    <Link
                                      key={callId}
                                      className="call-history__link"
                                      to={`/post-call-analysis?call_id=${encodeURIComponent(callId)}`}
                                      title={callId}
                                    >
                                      Call {index + 1}
                                    </Link>
                                  ))}
                                </span>
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                      {cause.undescribed > 0 && (
                        <p className="customer-panel__muted">
                          {cause.undescribed} not described in a call summary.
                        </p>
                      )}
                    </article>
                  ))}
                </div>
              </section>
            </>
          )}
        </>
      )}
    </section>
  )
}
