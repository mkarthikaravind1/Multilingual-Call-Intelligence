import type { JwtClaims, UserRole } from '../api/types/auth'

export const AUTH_SESSION_KEY = 'multilingual_auth_session'

export interface AuthSessionState {
  accessToken: string
  role: UserRole | null
  expiresAt: number | null
  provisional: boolean
}

export function decodeJwtClaims(token: string): JwtClaims {
  const parts = token.split('.')
  if (parts.length < 2) {
    return {}
  }

  const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
  const normalized = payload.padEnd(Math.ceil(payload.length / 4) * 4, '=')

  try {
    const decoded = atob(normalized)
    return JSON.parse(decoded) as JwtClaims
  } catch {
    return {}
  }
}

export function readSessionToken(): string | null {
  try {
    const raw = sessionStorage.getItem(AUTH_SESSION_KEY)
    if (!raw) {
      return null
    }

    const parsed = JSON.parse(raw) as { accessToken?: string }
    return typeof parsed.accessToken === 'string' ? parsed.accessToken : null
  } catch {
    sessionStorage.removeItem(AUTH_SESSION_KEY)
    return null
  }
}

export function writeSessionToken(token: string) {
  sessionStorage.setItem(AUTH_SESSION_KEY, JSON.stringify({ accessToken: token }))
}

export function clearSessionStorage() {
  sessionStorage.removeItem(AUTH_SESSION_KEY)
}
