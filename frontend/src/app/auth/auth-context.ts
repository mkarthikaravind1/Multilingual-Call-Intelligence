import { createContext } from 'react'

import type { AuthSessionState } from './session'

export interface AuthContextValue {
  session: AuthSessionState | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  clearUnauthorized: () => void
  statusMessage: string | null
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
