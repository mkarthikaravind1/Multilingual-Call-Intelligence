import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'

import { ApiError } from '../api/errors'
import { RecordTime } from '../components/RecordTime'
import { StatePanel } from '../components/StatePanel'
import { PriceListIssues } from '../features/price-list/components/PriceListIssues'
import { PriceListRowEditor } from '../features/price-list/components/PriceListRowEditor'
import { PriceListRowsTable } from '../features/price-list/components/PriceListRowsTable'
import { priceListRestService } from '../features/price-list/services/priceListRestService'

import type {
  InvalidPriceListDto,
  PriceListDto,
  PriceListIssueDto,
  PriceListPreviewDto,
  PriceListRowDto,
  PriceListSettingsDto,
  PriceListVersionDto,
} from '../features/price-list/types/dto'

const PAGE_SIZE = 100

const SOURCE_LABELS: Record<string, string> = {
  upload: 'Uploaded',
  edit: 'Edited',
  restore: 'Restored',
}

const errorMessage = (err: unknown, fallback: string) =>
  err instanceof ApiError ? err.message : fallback

// The row problems of a rejected save (422), if the server listed them.
const rejectedIssues = (err: unknown): PriceListIssueDto[] => {
  if (err instanceof ApiError && err.status === 422 && err.payload) {
    const errors = (err.payload as Partial<InvalidPriceListDto>).errors
    return Array.isArray(errors) ? errors : []
  }
  return []
}

const sequence = (length: number) => Array.from({ length }, (_, index) => index + 1)

const matches = (row: PriceListRowDto, query: string) =>
  [row.vehicle_model, row.service, row.part, ...row.keywords]
    .filter(Boolean)
    .some((value) => value!.toLowerCase().includes(query))

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

type Editor = { mode: 'add' } | { mode: 'edit'; index: number } | null

export function PriceListPage() {
  const [priceList, setPriceList] = useState<PriceListDto | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Unsaved changes: edited rows (null = none) and settings.
  const [draftRows, setDraftRows] = useState<PriceListRowDto[] | null>(null)
  const [settings, setSettings] = useState<PriceListSettingsDto | null>(null)
  const [editor, setEditor] = useState<Editor>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveIssues, setSaveIssues] = useState<PriceListIssueDto[]>([])
  const [notice, setNotice] = useState<string | null>(null)

  const [query, setQuery] = useState('')
  const [shown, setShown] = useState(PAGE_SIZE)

  const fileInput = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<PriceListPreviewDto | null>(null)
  const [previewFile, setPreviewFile] = useState<string | null>(null)
  const [isReading, setIsReading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const [versions, setVersions] = useState<PriceListVersionDto[]>([])
  const [restoringId, setRestoringId] = useState<number | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)

  const loadVersions = useCallback(async () => {
    try {
      setVersions(await priceListRestService.listVersions())
      setHistoryError(null)
    } catch (err) {
      setHistoryError(errorMessage(err, 'Unable to load the price list history.'))
    }
  }, [])

  const applySaved = useCallback((saved: PriceListDto) => {
    setPriceList(saved)
    setSettings(saved.settings)
    setDraftRows(null)
    setEditor(null)
    setSaveIssues([])
    setSaveError(null)
  }, [])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      void loadVersions()
      try {
        const loaded = await priceListRestService.get()
        if (!cancelled) {
          applySaved(loaded)
          setLoadError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(errorMessage(err, 'Unable to load the price list.'))
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [loadVersions, applySaved])

  const rows = useMemo(() => draftRows ?? priceList?.rows ?? [], [draftRows, priceList])
  const settingsChanged =
    priceList !== null &&
    settings !== null &&
    JSON.stringify(settings) !== JSON.stringify(priceList.settings)
  const isDirty = draftRows !== null || settingsChanged

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return rows.flatMap((row, index) => (!needle || matches(row, needle) ? [index] : []))
  }, [rows, query])

  const changeRows = (change: (current: PriceListRowDto[]) => PriceListRowDto[]) => {
    setDraftRows((current) => change(current ?? priceList?.rows ?? []))
    setNotice(null)
  }

  const save = async (
    rowsToSave: PriceListRowDto[],
    source: 'edit' | 'upload',
    note: string | null,
    done: string,
  ) => {
    if (!settings) {
      return false
    }
    setIsSaving(true)
    setSaveError(null)
    setSaveIssues([])
    setNotice(null)
    try {
      applySaved(await priceListRestService.save({ settings, rows: rowsToSave, source, note }))
      setNotice(done)
      void loadVersions()
      return true
    } catch (err) {
      setSaveError(errorMessage(err, 'Unable to save the price list.'))
      setSaveIssues(rejectedIssues(err))
      return false
    } finally {
      setIsSaving(false)
    }
  }

  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) {
      return
    }
    setIsReading(true)
    setUploadError(null)
    setPreview(null)
    setNotice(null)
    try {
      setPreview(await priceListRestService.preview(file))
      setPreviewFile(file.name)
    } catch (err) {
      setUploadError(errorMessage(err, 'Unable to read the file.'))
    } finally {
      setIsReading(false)
    }
  }

  const applyUpload = async () => {
    if (!preview) {
      return
    }
    const saved = await save(
      preview.rows,
      'upload',
      previewFile,
      `The price list from ${previewFile ?? 'the file'} is now in use.`,
    )
    if (saved) {
      setPreview(null)
      setPreviewFile(null)
    }
  }

  const download = async (format: 'xlsx' | 'csv') => {
    try {
      saveFile(await priceListRestService.export(format), `price-list.${format}`)
    } catch (err) {
      setSaveError(errorMessage(err, 'Unable to download the price list.'))
    }
  }

  const restore = async (version: PriceListVersionDto) => {
    if (
      isDirty &&
      !window.confirm('Restoring discards your unsaved changes. Continue?')
    ) {
      return
    }
    setRestoringId(version.version_id)
    setHistoryError(null)
    setNotice(null)
    try {
      applySaved(await priceListRestService.restore(version.version_id))
      setNotice(`Version ${version.version_id} is in use again.`)
      void loadVersions()
    } catch (err) {
      setHistoryError(errorMessage(err, 'Unable to restore that version.'))
    } finally {
      setRestoringId(null)
    }
  }

  if (isLoading) {
    return (
      <section className="page-shell">
        <StatePanel variant="loading" title="Loading the price list…" />
      </section>
    )
  }
  if (loadError || !priceList || !settings) {
    return (
      <section className="page-shell">
        <StatePanel
          variant="error"
          title="Could not load the price list"
          description={loadError ?? undefined}
        />
      </section>
    )
  }

  const setSetting = (key: keyof PriceListSettingsDto) => (event: ChangeEvent<HTMLInputElement>) =>
    setSettings((current) => (current ? { ...current, [key]: event.target.value } : current))

  return (
    <section className="page-shell">
      <section className="panel">
        <div className="section-heading">
          <h3 className="section-title">Price list</h3>
          <div className="list-card__meta">
            {priceList.version ? (
              <span className="badge badge--success">Version {priceList.version.version_id}</span>
            ) : (
              <span className="badge badge--warning">Sample prices</span>
            )}
            <span className="badge">{priceList.service_count} services</span>
            <span className="badge">{priceList.vehicle_model_count} vehicle models</span>
          </div>
        </div>
        <p className="customer-panel__muted">
          Call estimates are priced from this list. Prices are before GST: GST is added on top
          using each row's GST %. A vehicle model's own rows are used for calls about that
          model; other models get the rows with a blank vehicle model, marked approximate.
        </p>
        {!priceList.version && (
          <p className="inline-notice">
            These are sample prices. Download the sheet, fill in your service centre's prices
            and upload it.
          </p>
        )}
        {priceList.version && (
          <p className="customer-panel__muted">
            {SOURCE_LABELS[priceList.version.source] ?? priceList.version.source} by{' '}
            {priceList.version.created_by ?? 'unknown'} on{' '}
            <RecordTime seconds={priceList.version.created_at} />
            {priceList.version.note ? ` (${priceList.version.note})` : ''}
          </p>
        )}
        {notice && <p className="inline-notice inline-notice--success">{notice}</p>}
        <PriceListIssues issues={priceList.warnings} />
      </section>

      <section className="panel">
        <div className="section-heading">
          <h3 className="section-title">Upload from Excel</h3>
        </div>
        <p className="customer-panel__muted">
          One row per vehicle model, service and part. Download the current list to use as
          the template (its second sheet explains each column). Uploading replaces the whole
          list after you check the preview.
        </p>
        <div className="button-row">
          <button type="button" className="button button--secondary" onClick={() => void download('xlsx')}>
            Download Excel (.xlsx)
          </button>
          <button type="button" className="button button--secondary" onClick={() => void download('csv')}>
            Download CSV
          </button>
          <button
            type="button"
            className="button"
            disabled={isReading || isSaving}
            onClick={() => fileInput.current?.click()}
          >
            {isReading ? 'Reading…' : 'Upload .xlsx / .csv'}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".xlsx,.xlsm,.csv"
            hidden
            onChange={(event) => void handleFile(event)}
          />
        </div>
        {uploadError && (
          <p className="review-form__error" role="alert">
            {uploadError}
          </p>
        )}

        {preview && (
          <div className="price-list__preview">
            <p className="panel__label">Preview of {previewFile}</p>
            <p className="customer-panel__muted">
              {preview.rows.length} rows · {preview.service_count} services ·{' '}
              {preview.vehicle_model_count} vehicle models
            </p>
            <PriceListIssues issues={[...preview.errors, ...preview.warnings]} rowLabel="Sheet row" />
            {saveIssues.length > 0 && <PriceListIssues issues={saveIssues} />}
            <PriceListRowsTable
              rows={preview.rows}
              rowNumbers={preview.sheet_rows}
              visible={sequence(Math.min(preview.rows.length, PAGE_SIZE)).map((n) => n - 1)}
              issues={preview.errors}
            />
            {preview.rows.length > PAGE_SIZE && (
              <p className="customer-panel__muted">
                Showing the first {PAGE_SIZE} of {preview.rows.length} rows.
              </p>
            )}
            <div className="button-row">
              <button
                type="button"
                className="button"
                disabled={preview.errors.length > 0 || isSaving}
                onClick={() => {
                  if (
                    !isDirty ||
                    window.confirm('Replacing the price list discards your unsaved edits. Continue?')
                  ) {
                    void applyUpload()
                  }
                }}
              >
                {isSaving ? 'Saving…' : 'Replace the price list'}
              </button>
              <button
                type="button"
                className="button button--secondary"
                disabled={isSaving}
                onClick={() => {
                  setPreview(null)
                  setPreviewFile(null)
                }}
              >
                Cancel
              </button>
            </div>
            {preview.errors.length > 0 && (
              <p className="customer-panel__muted">
                Fix the problems in the sheet and upload it again.
              </p>
            )}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="section-heading">
          <h3 className="section-title">Labour and GST</h3>
        </div>
        <div className="price-list__settings">
          <label className="price-list__field">
            <span>Labour rate per hour</span>
            <input inputMode="decimal" value={settings.labour_hourly_rate} onChange={setSetting('labour_hourly_rate')} />
          </label>
          <label className="price-list__field">
            <span>Labour GST %</span>
            <input inputMode="decimal" value={settings.labour_gst_percent} onChange={setSetting('labour_gst_percent')} />
          </label>
          <label className="price-list__field">
            <span>Default part GST %</span>
            <input inputMode="decimal" value={settings.default_gst_percent} onChange={setSetting('default_gst_percent')} />
          </label>
          <label className="price-list__field">
            <span>Currency</span>
            <input maxLength={8} value={settings.currency} onChange={setSetting('currency')} />
          </label>
        </div>
        <p className="customer-panel__muted">
          The default part GST % applies to rows whose GST % is blank.
        </p>
      </section>

      <section className="panel">
        <div className="section-heading">
          <h3 className="section-title">Rows</h3>
          <div className="button-row">
            <input
              className="price-list__search"
              type="search"
              placeholder="Search model, service or part"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setShown(PAGE_SIZE)
              }}
            />
            <button
              type="button"
              className="button button--secondary"
              disabled={isSaving}
              onClick={() => setEditor({ mode: 'add' })}
            >
              Add row
            </button>
          </div>
        </div>

        {editor && (
          <PriceListRowEditor
            key={editor.mode === 'edit' ? `edit-${editor.index}` : 'add'}
            initial={editor.mode === 'edit' ? rows[editor.index] : null}
            onCancel={() => setEditor(null)}
            onSubmit={(row) => {
              if (editor.mode === 'edit') {
                const index = editor.index
                changeRows((current) => current.map((item, i) => (i === index ? row : item)))
              } else {
                changeRows((current) => [...current, row])
              }
              setEditor(null)
            }}
          />
        )}

        <PriceListRowsTable
          rows={rows}
          rowNumbers={sequence(rows.length)}
          visible={filtered.slice(0, shown)}
          issues={saveIssues}
          onEdit={(index) => setEditor({ mode: 'edit', index })}
          onDelete={(index) => {
            setEditor(null)
            changeRows((current) => current.filter((_, i) => i !== index))
          }}
        />
        {filtered.length === 0 && <p className="customer-panel__muted">No rows match.</p>}
        {filtered.length > shown && (
          <button
            type="button"
            className="button button--secondary spaced-top"
            onClick={() => setShown((current) => current + PAGE_SIZE)}
          >
            Show more ({filtered.length - shown} left)
          </button>
        )}
      </section>

      {(isDirty || saveError) && (
        <section className="panel price-list__save-bar">
          {isDirty && <p className="inline-notice">You have unsaved changes to the price list.</p>}
          {saveError && (
            <p className="review-form__error" role="alert">
              {saveError}
            </p>
          )}
          {!preview && <PriceListIssues issues={saveIssues} />}
          {isDirty && (
            <div className="button-row">
              <button
                type="button"
                className="button"
                disabled={isSaving}
                onClick={() => void save(rows, 'edit', null, 'Your changes are saved and in use.')}
              >
                {isSaving ? 'Saving…' : 'Save changes'}
              </button>
              <button
                type="button"
                className="button button--secondary"
                disabled={isSaving}
                onClick={() => applySaved(priceList)}
              >
                Discard changes
              </button>
            </div>
          )}
        </section>
      )}

      <section className="panel">
        <div className="section-heading">
          <h3 className="section-title">History</h3>
        </div>
        {historyError && (
          <p className="review-form__error" role="alert">
            {historyError}
          </p>
        )}
        {versions.length === 0 ? (
          <p className="customer-panel__muted">No saved versions yet.</p>
        ) : (
          <div className="card-stack">
            {versions.map((version) => (
              <article key={version.version_id} className="list-card">
                <div className="section-heading complaint-card__heading">
                  <strong className="list-card__title">Version {version.version_id}</strong>
                  <div className="list-card__meta">
                    {version.is_active && <span className="badge badge--active">In use</span>}
                    <span className="badge">{SOURCE_LABELS[version.source] ?? version.source}</span>
                    <span className="badge">{version.row_count} rows</span>
                  </div>
                </div>
                <div className="list-card__facts">
                  <span>
                    {version.created_by ?? 'unknown'} · <RecordTime seconds={version.created_at} />
                    {version.note ? ` · ${version.note}` : ''}
                  </span>
                </div>
                {!version.is_active && (
                  <div className="button-row">
                    <button
                      type="button"
                      className="button button--secondary"
                      disabled={restoringId !== null || isSaving}
                      onClick={() => void restore(version)}
                    >
                      {restoringId === version.version_id ? 'Restoring…' : 'Restore this version'}
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  )
}
