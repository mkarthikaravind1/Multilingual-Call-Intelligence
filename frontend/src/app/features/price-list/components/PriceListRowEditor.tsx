import { useState, type FormEvent } from 'react'

import type { PriceListRowDto } from '../types/dto'

type PriceListRowEditorProps = {
  initial: PriceListRowDto | null
  onSubmit: (row: PriceListRowDto) => void
  onCancel: () => void
}

type FormState = Record<
  | 'vehicle_model'
  | 'service'
  | 'part'
  | 'quantity'
  | 'unit_price'
  | 'gst_percent'
  | 'labour_hours'
  | 'duration_hours'
  | 'keywords'
  | 'includes',
  string
>

const toForm = (row: PriceListRowDto | null): FormState => ({
  vehicle_model: row?.vehicle_model ?? '',
  service: row?.service ?? '',
  part: row?.part ?? '',
  quantity: row?.quantity?.toString() ?? '',
  unit_price: row?.unit_price ?? '',
  gst_percent: row?.gst_percent ?? '',
  labour_hours: row?.labour_hours?.toString() ?? '',
  duration_hours: row?.duration_hours?.toString() ?? '',
  keywords: row?.keywords.join(', ') ?? '',
  includes: row?.includes.join(', ') ?? '',
})

const blankToNull = (value: string) => (value.trim() ? value.trim() : null)

// Blank is null; anything else that is not a number is NaN, which the form
// rejects, so a typo is reported rather than silently dropped.
const toNumber = (value: string): number | null => {
  if (!value.trim()) {
    return null
  }
  const number = Number(value.trim())
  return Number.isFinite(number) ? number : Number.NaN
}

const splitList = (value: string) =>
  value
    .split(/[;,]/)
    .map((item) => item.trim())
    .filter(Boolean)

const FIELDS: { key: keyof FormState; label: string; hint?: string }[] = [
  { key: 'vehicle_model', label: 'Vehicle model', hint: 'Blank = all models' },
  { key: 'service', label: 'Service' },
  { key: 'part', label: 'Part', hint: 'Blank = labour/settings only' },
  { key: 'quantity', label: 'Qty', hint: 'Default 1' },
  { key: 'unit_price', label: 'Unit price (excl. GST)' },
  { key: 'gst_percent', label: 'GST %', hint: 'Blank = default GST %' },
  { key: 'labour_hours', label: 'Labour hours' },
  { key: 'duration_hours', label: 'Duration hours', hint: 'Default = labour hours' },
  { key: 'keywords', label: 'Keywords', hint: 'Comma separated' },
  { key: 'includes', label: 'Includes services', hint: 'Comma separated' },
]

// Adds or edits one row of the price list draft; the server checks the
// values when the draft is saved.
export function PriceListRowEditor({ initial, onSubmit, onCancel }: PriceListRowEditorProps) {
  const [form, setForm] = useState<FormState>(() => toForm(initial))
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    const numbers = {
      quantity: toNumber(form.quantity),
      labour_hours: toNumber(form.labour_hours),
      duration_hours: toNumber(form.duration_hours),
    }
    if (!form.service.trim()) {
      setError('Service is required.')
      return
    }
    if (Object.values(numbers).some((value) => Number.isNaN(value))) {
      setError('Qty, labour hours and duration hours must be numbers.')
      return
    }
    if (numbers.quantity !== null && !Number.isInteger(numbers.quantity)) {
      setError('Qty must be a whole number.')
      return
    }
    onSubmit({
      service: form.service.trim(),
      vehicle_model: blankToNull(form.vehicle_model),
      part: blankToNull(form.part),
      quantity: numbers.quantity,
      unit_price: blankToNull(form.unit_price.replace(/[₹,\s]/g, '')),
      gst_percent: blankToNull(form.gst_percent.replace(/[%\s]/g, '')),
      labour_hours: numbers.labour_hours,
      duration_hours: numbers.duration_hours,
      keywords: splitList(form.keywords),
      includes: splitList(form.includes),
    })
  }

  return (
    <form className="price-list__editor" onSubmit={handleSubmit}>
      <p className="panel__label">{initial ? 'Edit row' : 'Add a row'}</p>
      <div className="price-list__editor-grid">
        {FIELDS.map(({ key, label, hint }) => (
          <label key={key} className="price-list__field">
            <span>{label}</span>
            <input
              value={form[key]}
              placeholder={hint}
              inputMode={
                ['quantity', 'unit_price', 'gst_percent', 'labour_hours', 'duration_hours'].includes(
                  key,
                )
                  ? 'decimal'
                  : undefined
              }
              onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))}
            />
          </label>
        ))}
      </div>
      {error && (
        <p className="review-form__error" role="alert">
          {error}
        </p>
      )}
      <div className="button-row">
        <button type="submit" className="button">
          {initial ? 'Update row' : 'Add row'}
        </button>
        <button type="button" className="button button--secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
