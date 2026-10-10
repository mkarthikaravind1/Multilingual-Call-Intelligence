import { useEffect, useState } from 'react'

import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import {
  reportRestService,
  type FiguresDto,
  type PerformanceReportDto,
  type ReportFilters,
} from '../services/reportRestService'

type PerformancePanelProps = {
  // null while the dates are not usable.
  filters: ReportFilters | null
  // For the downloaded file's name.
  fileLabel: string
}

// How each figure is worked out; keep in step with the backend's rules
// (app/services/performance.py).
const RULES: Array<{ name: string; rule: string }> = [
  {
    name: 'Coverage score',
    rule: 'Of the complaints raised on the calls, the share the executive asked the customer about. Whether a complaint was asked about is the AI’s reading of the call.',
  },
  {
    name: 'First Call Resolution',
    rule: 'Of calls with a complaint from a known customer, the share where that customer did not call again about the same category within 7 days. Calls from the last 7 days are not counted yet.',
  },
  {
    name: 'Repeat complaints',
    rule: 'Of complaints from known customers, the share where the same customer raised the same category in the 30 days before.',
  },
  {
    name: 'Churn risk',
    rule: 'Points per call: tone negative 1, frustrated 2, escalating 3; a high or critical escalation 2; a repeat complaint 2; any complaint still open 1. Low is 0–1, medium 2–3, high 4 or more.',
  },
  {
    name: 'CSAT estimate',
    rule: 'From the call’s tone (positive 4.5, neutral 3.5, negative 2.5, frustrated 2.0, escalating 1.5), minus 0.5 with a complaint still open, plus 0.5 when all its complaints are resolved, minus 0.5 for a high or critical escalation; kept between 1 and 5. Only calls with a tone are counted.',
  },
]

const percent = (rate: number | null) => (rate === null ? '—' : `${Math.round(rate * 100)}%`)
const score = (value: number | null) => (value === null ? '—' : value.toFixed(1))

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

function Tile({ label, value, basis }: { label: string; value: string; basis: string }) {
  return (
    <div className="report-tile">
      <span>
        {label} <em className="report-estimate">estimate</em>
      </span>
      <strong>{value}</strong>
      <small>{basis}</small>
    </div>
  )
}

function ChurnBar({ figures }: { figures: FiguresDto }) {
  const parts = [
    { key: 'low', label: 'Low', count: figures.churn_low },
    { key: 'medium', label: 'Medium', count: figures.churn_medium },
    { key: 'high', label: 'High', count: figures.churn_high },
  ]
  return (
    <div className="churn">
      <div className="churn__bar" aria-hidden="true">
        {parts
          .filter((part) => part.count > 0)
          .map((part) => (
            <span
              key={part.key}
              className={`churn__part churn__part--${part.key}`}
              style={{ flexGrow: part.count }}
              title={`${part.label} risk: ${part.count} calls`}
            />
          ))}
      </div>
      <ul className="churn__legend">
        {parts.map((part) => (
          <li key={part.key}>
            <span className={`churn__swatch churn__part--${part.key}`} aria-hidden="true" />
            {part.label} risk: <strong>{part.count}</strong> calls
          </li>
        ))}
      </ul>
    </div>
  )
}

type Loaded = { key: string; report: PerformanceReportDto | null; error: string | null }

export function PerformancePanel({ filters, fileLabel }: PerformancePanelProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const filterKey = filters ? JSON.stringify(filters) : ''

  useEffect(() => {
    if (!filterKey) return
    let cancelled = false
    reportRestService
      .getPerformanceReport(JSON.parse(filterKey) as ReportFilters)
      .then((report) => {
        if (!cancelled) setLoaded({ key: filterKey, report, error: null })
      })
      .catch((err) => {
        if (cancelled) return
        setLoaded({
          key: filterKey,
          report: null,
          error: err instanceof ApiError ? err.message : 'Unable to load the figures.',
        })
      })
    return () => {
      cancelled = true
    }
  }, [filterKey])

  const download = async (format: 'csv' | 'xlsx') => {
    if (!filters) return
    setExporting(format)
    setExportError(null)
    try {
      const blob = await reportRestService.exportScorecard(filters, format)
      saveFile(blob, `executive-scorecard-${fileLabel}.${format}`)
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Unable to download the scorecard.')
    } finally {
      setExporting(null)
    }
  }

  if (!filters) return null
  if (!loaded) return <StatePanel variant="loading" title="Loading the figures…" compact />
  if (loaded.error || !loaded.report) {
    return (
      <StatePanel
        variant="error"
        title="Could not load the figures"
        description={loaded.error ?? ''}
      />
    )
  }

  const { overall, executives } = loaded.report
  const isStale = loaded.key !== filterKey

  return (
    <>
      <p className="inline-notice">
        These figures are <strong>estimates</strong>, worked out by fixed rules from what the
        calls recorded. No customer was asked. The rules are listed at the bottom of the page.
      </p>

      <div className={`report-tiles${isStale ? ' report-tiles--stale' : ''}`}>
        <Tile
          label="Coverage score"
          value={percent(overall.coverage_score)}
          basis={`${overall.probed_complaints} of ${overall.complaints} complaints asked about`}
        />
        <Tile
          label="First Call Resolution"
          value={percent(overall.fcr_rate)}
          basis={`${overall.fcr_resolved} of ${overall.fcr_calls} calls judged`}
        />
        <Tile
          label="Repeat complaints"
          value={percent(overall.repeat_rate)}
          basis={`${overall.repeat_complaints} of ${overall.known_customer_complaints} from known customers`}
        />
        <Tile
          label="CSAT"
          value={overall.csat === null ? '—' : `${score(overall.csat)} / 5`}
          basis={`${overall.rated_calls} calls with a tone`}
        />
      </div>

      {overall.calls === 0 ? (
        <StatePanel
          title="No calls match these filters"
          description="Try a wider date range or fewer filters."
          compact
        />
      ) : (
        <>
          <section className="panel">
            <div className="section-heading">
              <h3 className="section-title">Churn risk</h3>
              <span className="customer-panel__muted">
                Estimate, per call · {overall.calls} calls
              </span>
            </div>
            <ChurnBar figures={overall} />
          </section>

          <section className="panel">
            <div className="section-heading">
              <h3 className="section-title">Executive scorecard</h3>
              <div className="button-row">
                {(['xlsx', 'csv'] as const).map((format) => (
                  <button
                    key={format}
                    type="button"
                    className="button button--secondary"
                    disabled={exporting !== null}
                    onClick={() => void download(format)}
                  >
                    {exporting === format ? 'Preparing…' : format === 'xlsx' ? 'Excel' : 'CSV'}
                  </button>
                ))}
              </div>
            </div>
            {exportError && (
              <p className="review-form__error" role="alert">
                {exportError}
              </p>
            )}
            <div className="report-table-scroll">
              <table className="report-table report-scorecard">
                <thead>
                  <tr>
                    <th scope="col">Executive</th>
                    <th scope="col">Calls</th>
                    <th scope="col">Complaints</th>
                    <th scope="col">Coverage</th>
                    <th scope="col">First Call Resolution</th>
                    <th scope="col">Repeat complaints</th>
                    <th scope="col">CSAT</th>
                    <th scope="col">Negative or worse</th>
                    <th scope="col">High churn risk</th>
                    <th scope="col">High or critical escalations</th>
                    <th scope="col">Questions accepted / skipped</th>
                  </tr>
                </thead>
                <tbody>
                  {executives.map(({ executive_user_id, name, figures }) => (
                    <tr key={executive_user_id ?? 'none'}>
                      <th scope="row">{name}</th>
                      <td>{figures.calls}</td>
                      <td>{figures.complaints}</td>
                      <td title={`${figures.probed_complaints} of ${figures.complaints} complaints asked about`}>
                        {percent(figures.coverage_score)}
                      </td>
                      <td title={`${figures.fcr_resolved} of ${figures.fcr_calls} calls judged`}>
                        {percent(figures.fcr_rate)}
                      </td>
                      <td title={`${figures.repeat_complaints} of ${figures.known_customer_complaints} complaints from known customers`}>
                        {percent(figures.repeat_rate)}
                      </td>
                      <td>{score(figures.csat)}</td>
                      <td title={`of ${figures.rated_calls} calls with a tone`}>
                        {figures.negative_calls}
                      </td>
                      <td>{figures.churn_high}</td>
                      <td>{figures.serious_escalations}</td>
                      <td>
                        {figures.questions_accepted} / {figures.questions_skipped}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <section className="panel">
        <h3 className="section-title">How these estimates are worked out</h3>
        <dl className="report-rules">
          {RULES.map(({ name, rule }) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{rule}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  )
}
