// Maps backend values to a visual tone (badge/indicator colour).
export type Tone = 'success' | 'warning' | 'danger' | 'neutral'

const COMPLAINT_STATUS_TONES: Record<string, Tone> = {
  detected: 'warning',
  probed: 'warning',
  unresolved: 'danger',
  covered: 'success',
  resolved: 'success',
}

const SENTIMENT_TONES: Record<string, Tone> = {
  POSITIVE: 'success',
  NEGATIVE: 'danger',
}

export function complaintStatusTone(status: string): Tone {
  return COMPLAINT_STATUS_TONES[status.toLowerCase()] ?? 'neutral'
}

export function sentimentTone(label: string): Tone {
  return SENTIMENT_TONES[label.toUpperCase()] ?? 'neutral'
}
