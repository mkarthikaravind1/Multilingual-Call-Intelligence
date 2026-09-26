import { useCallback, useMemo, useState } from 'react'

import { apiClient } from '../api/client'
import { ApiError } from '../api/errors'
import type { AuthContextValue } from './auth-context'
import { AuthContext } from './auth-context'
import { authService } from './AuthService'
import type { AuthSessionState } from './session'

export type { AuthContextValue } from './auth-context'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSessionState | null>(() => authService.getSession())
  const [isLoading, setIsLoading] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  apiClient.setErrorHandlers({
    onUnauthorized: () => {
      authService.logout()
      setSession(null)
      setStatusMessage('Your session has expired. Please sign in again.')
    },
    onForbidden: () => {
      setStatusMessage('You do not have permission to access this resource.')
    },
  })

  const clearUnauthorized = useCallback(() => {
    authService.logout()
    setSession(null)
    setStatusMessage('Your session has expired. Please sign in again.')
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    setIsLoading(true)
    setStatusMessage(null)

    try {
      const nextSession = await authService.login(email, password)
      setSession(nextSession)
    } catch (error) {
      if (error instanceof ApiError) {
        setStatusMessage(error.message)
      } else {
        setStatusMessage('Unable to sign in. Please try again.')
      }
      throw error
    } finally {
      setIsLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    authService.logout()
    setSession(null)
    setStatusMessage(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isAuthenticated: authService.isAuthenticated(),
      isLoading,
      login,
      logout,
      clearUnauthorized,
      statusMessage,
    }),
    [clearUnauthorized, isLoading, login, logout, session, statusMessage],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

