import { apiClient } from '../api/client'
import type { LoginRequest, TokenResponse, UserRole } from '../api/types/auth'
import { AUTH_ROLES } from '../api/types/auth'
import { clearSessionStorage, decodeJwtClaims, readSessionToken, writeSessionToken, type AuthSessionState } from './session'

export class AuthService {
  private session: AuthSessionState | null = null

  constructor() {
    this.restoreSession()
  }

  getSession(): AuthSessionState | null {
    return this.session
  }

  isAuthenticated(): boolean {
    if (!this.session?.accessToken) {
      return false
    }

    if (!this.session.expiresAt) {
      return true
    }

    return Date.now() < this.session.expiresAt
  }

  getRole(): UserRole | null {
    return this.session?.role ?? null
  }

  hasRole(requiredRole: UserRole): boolean {
    return this.session?.role === requiredRole
  }

  getAccessToken(): string | null {
    return this.session?.accessToken ?? null
  }

  async login(email: string, password: string): Promise<AuthSessionState> {
    const payload: LoginRequest = { email, password }
    const response = await apiClient.post<TokenResponse>('/api/v1/auth/login', payload)
    const accessToken = response.access_token

    const claims = decodeJwtClaims(accessToken)
    const role = this.resolveRole(claims.role)

    this.session = {
      accessToken,
      role,
      expiresAt: typeof claims.exp === 'number' ? claims.exp * 1000 : null,
      provisional: true,
    }

    apiClient.setAccessToken(accessToken)
    writeSessionToken(accessToken)

    return this.session
  }

  restoreSession(): AuthSessionState | null {
    const token = readSessionToken()

    if (!token) {
      this.session = null
      apiClient.setAccessToken(null)
      return null
    }

    const claims = decodeJwtClaims(token)
    const expiresAt = typeof claims.exp === 'number' ? claims.exp * 1000 : null

    if (expiresAt !== null && expiresAt <= Date.now()) {
      this.logout()
      return null
    }

    const role = this.resolveRole(claims.role)

    this.session = {
      accessToken: token,
      role,
      expiresAt,
      provisional: true,
    }

    apiClient.setAccessToken(token)
    return this.session
  }

  logout(): void {
    this.session = null
    apiClient.setAccessToken(null)
    clearSessionStorage()
  }

  private resolveRole(rawRole: string | undefined): UserRole | null {
    if (!rawRole) {
      return null
    }

    return AUTH_ROLES.includes(rawRole as UserRole) ? (rawRole as UserRole) : null
  }
}

export const authService = new AuthService()
