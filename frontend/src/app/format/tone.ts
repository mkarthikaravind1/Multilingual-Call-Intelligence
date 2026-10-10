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
  FRUSTRATED: 'danger',
  ESCALATING: 'danger',
}

// The tone of one line of a call, mildest first. Each has its own colour
// on the transcript and its own height on the tone timeline.
export const LINE_TONES = ['positive', 'neutral', 'negative', 'frustrated', 'escalating'] as const
export type LineTone = (typeof LINE_TONES)[number]

// null: the line has not been rated (or carries a label this page does not know).
export function lineToneKey(label: string | null | undefined): LineTone | null {
  const key = (label ?? '').toLowerCase()
  return LINE_TONES.find((tone) => tone === key) ?? null
}

export function complaintStatusTone(status: string): Tone {
  return COMPLAINT_STATUS_TONES[status.toLowerCase()] ?? 'neutral'
}

export function sentimentTone(label: string): Tone {
  return SENTIMENT_TONES[label.toUpperCase()] ?? 'neutral'
}
