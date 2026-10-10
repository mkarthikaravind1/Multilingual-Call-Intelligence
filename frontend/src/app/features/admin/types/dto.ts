import type { UserRole } from '../../../api/types/auth'

export interface ManagedUserDto {
  user_id: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: number
  // Shown on calls and reports; null: the email is shown.
  display_name: string | null
  location_id: string | null
  // The phone number or SIP address the user's phone is reached at.
  dial_target: string | null
}

export interface CreateUserDto {
  email: string
  password: string
  role: UserRole
  display_name?: string | null
  location_id?: string | null
  dial_target?: string | null
}

// A field left out is unchanged; null clears it.
export interface UpdateUserDto {
  role?: UserRole
  is_active?: boolean
  display_name?: string | null
  location_id?: string | null
  dial_target?: string | null
}

export interface LocationDto {
  location_id: string
  name: string
  // The number customers dial, as "+<digits>".
  phone_number: string
  is_active: boolean
  created_at: number
}

export interface CreateLocationDto {
  name: string
  phone_number: string
}

export interface UpdateLocationDto {
  name?: string
  phone_number?: string
  is_active?: boolean
}

export interface PendingPostCallDto {
  call_id: string
  // When the repair sweep first noticed the call without a summary.
  first_seen_at: number
  attempts: number
  last_attempt_at: number | null
  last_error: string | null
  // Automatic retries have stopped; retry by hand.
  gave_up: boolean
}

export interface RepairRunDto {
  ran_at: number
  scanned: number
  pending: number
  repaired: number
  failed: number
  gave_up: number
  skipped_reason: string | null
}

export interface PostCallRepairStatusDto {
  pending: PendingPostCallDto[]
  last_run: RepairRunDto | null
  background_enabled: boolean
}

// A complaint category with what an administrator has decided about it.
export interface ManagedCategoryDto {
  // builtin:<name>, theme:<candidate id> or admin:<id>.
  key: string
  name: string
  // What counts as it, told to the AI; null for built-ins.
  description: string | null
  // built_in, theme (an accepted emerging theme) or admin (added here).
  source: string
  // Names it had before: complaints stored under them count under `name`.
  former_names: string[]
  // When it was retired; null: in use.
  retired_at: number | null
  can_rename: boolean
  can_retire: boolean
}

export interface CreateCategoryDto {
  name: string
  description?: string | null
}

// Each left out: unchanged.
export interface UpdateCategoryDto {
  name?: string
  description?: string | null
  // true: retire it; false: bring it back.
  retired?: boolean
}

export interface RetryPostCallDto {
  call_id: string
  repaired: boolean
}
