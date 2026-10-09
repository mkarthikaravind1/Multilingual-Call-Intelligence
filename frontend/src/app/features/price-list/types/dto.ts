// Amounts are backend Decimals, serialized as JSON strings. Prices are
// before GST.
export interface PriceListSettingsDto {
  currency: string
  labour_hourly_rate: string
  // GST on labour, and on parts whose row leaves GST % blank.
  labour_gst_percent: string
  default_gst_percent: string
}

// One row per vehicle model + service + part. Blank vehicle_model: the
// price for every model without rows of its own.
export interface PriceListRowDto {
  service: string
  vehicle_model: string | null
  part: string | null
  quantity: number | null
  unit_price: string | null
  gst_percent: string | null
  labour_hours: number | null
  duration_hours: number | null
  keywords: string[]
  includes: string[]
}

export interface PriceListIssueDto {
  severity: 'error' | 'warning'
  message: string
  // Row number (1-based); null for the list as a whole.
  row: number | null
}

export interface PriceListVersionDto {
  version_id: number
  created_at: number
  created_by: string | null
  source: 'upload' | 'edit' | 'restore' | string
  note: string | null
  row_count: number
  is_active: boolean
}

export interface PriceListDto {
  settings: PriceListSettingsDto
  rows: PriceListRowDto[]
  // null while the built-in sample price list is in use.
  version: PriceListVersionDto | null
  service_count: number
  vehicle_model_count: number
  warnings: PriceListIssueDto[]
}

export interface PriceListPreviewDto {
  rows: PriceListRowDto[]
  // The spreadsheet row each row came from; issues use these numbers.
  sheet_rows: number[]
  errors: PriceListIssueDto[]
  warnings: PriceListIssueDto[]
  service_count: number
  vehicle_model_count: number
}

export interface SavePriceListDto {
  settings: PriceListSettingsDto
  rows: PriceListRowDto[]
  source: 'edit' | 'upload'
  note?: string | null
}

// Body of a 422 when a save is rejected.
export interface InvalidPriceListDto {
  detail: string
  errors: PriceListIssueDto[]
}
