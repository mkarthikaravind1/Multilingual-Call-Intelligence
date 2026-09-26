export class ApiError extends Error {
  readonly status: number
  readonly detail?: string
  readonly payload?: unknown

  constructor(status: number, message: string, payload?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = message
    this.payload = payload
  }
}

export function getErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') {
    return fallback
  }

  const record = payload as Record<string, unknown>
  const detail = record.detail

  if (typeof detail === 'string') {
    return detail
  }

  if (Array.isArray(detail)) {
    const firstEntry = detail[0]
    if (firstEntry && typeof firstEntry === 'object') {
      const msg = (firstEntry as { msg?: unknown }).msg
      if (typeof msg === 'string') {
        return msg
      }
    }
  }

  if (typeof record.message === 'string') {
    return record.message
  }

  return fallback
}
