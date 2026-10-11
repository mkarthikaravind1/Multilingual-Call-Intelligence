export interface AuditEntryDto {
  entry_id: number | null
  occurred_at: number
  // The endpoint's name, e.g. "create_user".
  action: string
  method: string
  path: string
  status_code: number
  succeeded: boolean
  user_id: string | null
  // The user's name as it is now; null when nobody was signed in.
  user_name: string | null
  // "telephony" for the telephony provider's own requests.
  role: string | null
  target_type: string | null
  target_id: string | null
  ip_address: string | null
  request_id: string | null
  detail: Record<string, unknown> | null
}

export interface AuditLogDto {
  entries: AuditEntryDto[]
  total: number
  actions: string[]
  users: Array<{ user_id: string; name: string }>
  retention_days: number
}

// Times are epoch seconds: from inclusive, to exclusive.
export interface AuditLogFilters {
  userId?: string
  action?: string
  succeeded?: boolean
  targetId?: string
  occurredFrom?: number
  occurredTo?: number
}

export type AiOutcome = 'answered' | 'unusable' | 'failed'
// full: prompts and answers are kept; details: everything but their text.
export type AiLogMode = 'full' | 'details' | 'off'

export interface AiLogEntryDto {
  entry_id: string
  // null for work that belongs to no single call.
  call_id: string | null
  task: string
  model: string
  started_at: number
  duration_ms: number
  outcome: AiOutcome
  // 2: asked again because the first answer could not be used.
  attempt: number
  prompt_chars: number
  answer_chars: number
  prompt_tokens: number | null
  completion_tokens: number | null
  // Why it failed or could not be used.
  note: string | null
}

export interface AiLogEntryDetailDto extends AiLogEntryDto {
  prompt: string | null
  answer: string | null
}

export interface AiLogDto {
  entries: AiLogEntryDto[]
  total: number
  // Over everything the filters match, not only this page.
  totals: {
    requests: number
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    uncounted: number
  }
  tasks: string[]
  mode: AiLogMode
  retention_days: number
}

export interface AiLogFilters {
  callId?: string
  task?: string
  outcome?: AiOutcome
  startedFrom?: number
  startedTo?: number
}
