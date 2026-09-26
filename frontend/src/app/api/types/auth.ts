export const AUTH_ROLES = ['ICR', 'SUPERVISOR', 'ADMIN'] as const

export type UserRole = (typeof AUTH_ROLES)[number]

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface JwtClaims {
  sub?: string
  role?: UserRole | string
  exp?: number
  iat?: number
}
