export function formatElapsedSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return '0:00'
  }

  const totalSeconds = Math.floor(seconds)
  const minutes = Math.floor(totalSeconds / 60)
  const remainingSeconds = totalSeconds % 60

  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
}

// For backend record timestamps that are real epoch seconds (e.g. learning
// records, call start times, complaint resolution). Shows '—' for calls
// started without a wall-clock time (start_time 0).
export function formatRecordTimestamp(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return '—'
  }

  return new Date(seconds * 1000).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

// Call start/end times are not wall-clock dates for every call (calls
// started through the API without a time start at 0), but their difference
// is always the real duration.
export function formatCallDuration(
  startTime: number,
  endTime: number | null,
): string {
  if (endTime == null) {
    return 'In progress'
  }

  return formatElapsedSeconds(endTime - startTime)
}
