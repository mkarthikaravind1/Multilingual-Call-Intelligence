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
// records). Do not use it for call start/end times — see formatCallDuration.
export function formatRecordTimestamp(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return '—'
  }

  return new Date(seconds * 1000).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

// Call start/end times are not wall-clock dates for every call (telephony
// calls start at 0), but their difference is always the real duration.
export function formatCallDuration(
  startTime: number,
  endTime: number | null,
): string {
  if (endTime == null) {
    return 'In progress'
  }

  return formatElapsedSeconds(endTime - startTime)
}
