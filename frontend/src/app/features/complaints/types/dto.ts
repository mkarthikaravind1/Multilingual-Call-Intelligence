export type ComplaintStatus =
  | 'raised'
  | 'detected'
  | 'probed'
  | 'covered'
  | 'resolved'
  | 'unresolved'
  | 'follow_up'

// Statuses a person can set; the others are driven by the call.
export type ComplaintAction = 'resolved' | 'unresolved' | 'follow_up'

export type ComplaintQueueState = 'open' | 'resolved' | 'all'

export interface ComplaintEventDto {
  status: ComplaintStatus
  at: number
  // "system" for changes made by call analysis, otherwise the user's email.
  actor: string
  note: string | null
}

export interface ComplaintDto {
  // "<call_id>:<category>"
  complaint_id: string
  call_id: string
  category: string
  status: ComplaintStatus
  is_open: boolean
  follow_up_required: boolean
  customer_id: string | null
  first_detected_at: number
  last_updated_at: number
  allowed_actions: ComplaintAction[]
  // Oldest first.
  events: ComplaintEventDto[]
}

export interface CallComplaintsDto {
  call_id: string
  // null until the caller is matched to a CRM customer.
  customer_id: string | null
  complaints: ComplaintDto[]
  // The same customer's complaints from other calls, most recent first.
  customer_history: ComplaintDto[]
}

export type EmergingComplaintStatus = 'pending_review' | 'accepted' | 'rejected'

export interface EmergingComplaintDto {
  candidate_id: string
  proposed_name: string
  description: string
  evidence: string[]
  call_ids: string[]
  occurrence_count: number
  confidence: number
  related_category: string | null
  status: EmergingComplaintStatus
  first_seen_at: number
  last_seen_at: number
  reviewed_by: string | null
  reviewed_at: number | null
  review_note: string | null
}

export interface DiscoveryRunDto {
  ran_at: number
  calls_scanned: number
  candidates_found: number
  new_candidates: number
  // Why the discovery provider was not asked, e.g. too few calls.
  skipped_reason: string | null
}

export interface EmergingComplaintsDto {
  candidates: EmergingComplaintDto[]
  // null until discovery has run since the server started.
  last_run: DiscoveryRunDto | null
}
