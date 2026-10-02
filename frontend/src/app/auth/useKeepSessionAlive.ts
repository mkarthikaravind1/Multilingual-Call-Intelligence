import { useEffect } from 'react'

import { useAuth } from './useAuth'

// Renew this long before the token expires (or halfway through a shorter one).
const RENEW_BEFORE_EXPIRY_MS = 5 * 60 * 1000
const RETRY_AFTER_FAILURE_MS = 30 * 1000

// While `active` (e.g. a live call is in progress), renews the sign-in before
// it expires so the call is never interrupted by a session timeout. When not
// active, the normal expiry applies.
export function useKeepSessionAlive(active: boolean) {
  const { session, refreshSession } = useAuth()
  const expiresAt = session?.expiresAt ?? null

  useEffect(() => {
    if (!active || expiresAt === null) {
      return
    }

    let timer: number | undefined
    let cancelled = false

    const renew = () => {
      refreshSession().catch(() => {
        // A 401 signs the user out (see AuthProvider); anything else, such as
        // a network blip, is retried while the token is still valid.
        if (!cancelled && Date.now() + RETRY_AFTER_FAILURE_MS < expiresAt) {
          timer = window.setTimeout(renew, RETRY_AFTER_FAILURE_MS)
        }
      })
    }

    const remaining = expiresAt - Date.now()
    timer = window.setTimeout(
      renew,
      Math.max(remaining - RENEW_BEFORE_EXPIRY_MS, remaining / 2, 0),
    )

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [active, expiresAt, refreshSession])
}
