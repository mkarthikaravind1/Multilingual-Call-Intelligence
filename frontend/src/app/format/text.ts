// Turns backend enum values such as "pending_review" or "NOT_RAISED" into
// readable labels ("Pending review", "Not raised").
export function humanizeLabel(value: string): string {
  const words = value.replace(/[_-]+/g, ' ').trim().toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}
