import type { UserRole } from '../../../api/types/auth'

export interface ManagedUserDto {
  user_id: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: number
}

export interface CreateUserDto {
  email: string
  password: string
  role: UserRole
}

export interface UpdateUserDto {
  role?: UserRole
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

export interface RetryPostCallDto {
  call_id: string
  repaired: boolean
}
