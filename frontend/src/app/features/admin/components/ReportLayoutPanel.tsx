import { useEffect, useState, type FormEvent } from 'react'

import { apiClient } from '../../../api/client'
import { ApiError } from '../../../api/errors'
import { RecordTime } from '../../../components/RecordTime'
import { StatePanel } from '../../../components/StatePanel'

interface LayoutChoice {
  id: string
  name: string
  // False for a section the PDF leaves out (it is in Excel and CSV).
  in_pdf: boolean
}

interface ReportLayoutDto {
  company_name: string
  title: string
  // In the order they appear.
  sections: string[]
  columns: string[]
  available_sections: LayoutChoice[]
  available_columns: LayoutChoice[]
  // null while the built-in layout is in use.
  updated_at: number | null
  updated_by: string | null
}

const path = '/api/v1/admin/report-layout'

// The chosen ones in their order, then the rest in the built-in order.
function ordered(chosen: string[], available: LayoutChoice[]): LayoutChoice[] {
  const byId = new Map(available.map((choice) => [choice.id, choice]))
  const first = chosen.flatMap((id) => (byId.has(id) ? [byId.get(id)!] : []))
  return [...first, ...available.filter((choice) => !chosen.includes(choice.id))]
}

interface OrderedChoicesProps {
  legend: string
  hint: string
  available: LayoutChoice[]
  chosen: string[]
  disabled: boolean
  onChange: (chosen: string[]) => void
}

// Tick what the report has; the arrows move a ticked item up or down.
function OrderedChoices({ legend, hint, available, chosen, disabled, onChange }: OrderedChoicesProps) {
  const move = (id: string, by: number) => {
    const from = chosen.indexOf(id)
    const to = from + by
    if (from < 0 || to < 0 || to >= chosen.length) return
    const next = [...chosen]
    next.splice(to, 0, next.splice(from, 1)[0])
    onChange(next)
  }

  return (
    <fieldset className="report-layout__choices">
      <legend>{legend}</legend>
      <p className="customer-panel__muted">{hint}</p>
      <ol>
        {ordered(chosen, available).map((choice) => {
          const place = chosen.indexOf(choice.id)
          const isChosen = place >= 0
          return (
            <li key={choice.id} className={isChosen ? '' : 'report-layout__item--off'}>
              <label>
                <input
                  type="checkbox"
                  checked={isChosen}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange(
                      event.target.checked
                        ? [...chosen, choice.id]
                        : chosen.filter((id) => id !== choice.id),
                    )
                  }
                />
                {choice.name}
                {!choice.in_pdf && <small> (Excel and CSV only)</small>}
              </label>
              {isChosen && (
                <span className="report-layout__moves">
                  <button
                    type="button"
                    className="button button--secondary"
                    disabled={disabled || place === 0}
                    aria-label={`Move ${choice.name} up`}
                    onClick={() => move(choice.id, -1)}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="button button--secondary"
                    disabled={disabled || place === chosen.length - 1}
                    aria-label={`Move ${choice.name} down`}
                    onClick={() => move(choice.id, 1)}
                  >
                    ↓
                  </button>
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </fieldset>
  )
}

// What the exported complaint report carries: the company name and title,
// its sections in order, and the columns of its list of complaints.
export function ReportLayoutPanel() {
  const [saved, setSaved] = useState<ReportLayoutDto | null>(null)
  const [companyName, setCompanyName] = useState('')
  const [title, setTitle] = useState('')
  const [sections, setSections] = useState<string[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const show = (layout: ReportLayoutDto) => {
    setSaved(layout)
    setCompanyName(layout.company_name)
    setTitle(layout.title)
    setSections(layout.sections)
    setColumns(layout.columns)
  }

  useEffect(() => {
    let cancelled = false
    apiClient
      .get<ReportLayoutDto>(path)
      .then((layout) => {
        if (!cancelled) show(layout)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Unable to load the report layout.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const changed =
    saved !== null &&
    (companyName.trim() !== saved.company_name ||
      title.trim() !== saved.title ||
      sections.join() !== saved.sections.join() ||
      columns.join() !== saved.columns.join())

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setIsSaving(true)
    setError(null)
    setNotice(null)
    try {
      show(
        await apiClient.put<ReportLayoutDto>(path, {
          company_name: companyName.trim(),
          title: title.trim(),
          sections,
          columns,
        }),
      )
      setNotice('Saved. Downloads follow it from now on.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to save the report layout.')
    } finally {
      setIsSaving(false)
    }
  }

  const useBuiltIn = () => {
    if (!saved) return
    setCompanyName('')
    setTitle('Complaint report')
    setSections(saved.available_sections.map((choice) => choice.id))
    setColumns(saved.available_columns.map((choice) => choice.id))
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h3 className="section-title">Report layout</h3>
          <p className="customer-panel__muted">
            What the complaint report carries when it is downloaded from Reports as Excel, PDF or
            CSV. The Reports page itself always shows everything.
            {saved?.updated_at != null && (
              <>
                {' '}
                Last changed <RecordTime seconds={saved.updated_at} />.
              </>
            )}
          </p>
        </div>
      </div>

      {!saved && !error && <StatePanel compact variant="loading" title="Loading…" />}
      {!saved && error && (
        <StatePanel compact variant="error" title="Could not load the report layout" description={error} />
      )}

      {saved && (
        <form className="report-layout" onSubmit={(event) => void save(event)}>
          <div className="review-form">
            <label htmlFor="report-layout-company">Company name</label>
            <input
              id="report-layout-company"
              maxLength={100}
              placeholder="Printed above the title; leave empty for none"
              value={companyName}
              disabled={isSaving}
              onChange={(event) => setCompanyName(event.target.value)}
            />
            <label htmlFor="report-layout-title">Title</label>
            <input
              id="report-layout-title"
              maxLength={100}
              required
              value={title}
              disabled={isSaving}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>

          <div className="report-layout__lists">
            <OrderedChoices
              legend="Sections"
              hint="In Excel each is a sheet, in this order; in the PDF each is a part of the page."
              available={saved.available_sections}
              chosen={sections}
              disabled={isSaving}
              onChange={setSections}
            />
            <OrderedChoices
              legend="Columns of the list of complaints"
              hint="The CSV file is this list; in Excel it is the Complaints sheet."
              available={saved.available_columns}
              chosen={columns}
              disabled={isSaving}
              onChange={setColumns}
            />
          </div>

          {error && (
            <p className="review-form__error" role="alert">
              {error}
            </p>
          )}
          {notice && <p className="inline-notice inline-notice--success">{notice}</p>}

          <div className="button-row">
            <button
              type="submit"
              className="button"
              disabled={isSaving || !changed || sections.length === 0 || columns.length === 0}
            >
              {isSaving ? 'Saving…' : 'Save layout'}
            </button>
            <button
              type="button"
              className="button button--secondary"
              disabled={isSaving}
              onClick={useBuiltIn}
            >
              Use the built-in layout
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
