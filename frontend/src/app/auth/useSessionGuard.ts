import { useCallback, useEffect, useRef, useState } from 'react'

import { useAuth } from './useAuth'

// Shortly before the sign-in would end it is renewed, or the user is warned.
const ACT_BEFORE_EXPIRY_MS = 5 * 60 * 1000
// Someone who clicked or typed this recently is at work and is kept signed in.
const ACTIVE_WITHIN_MS = 10 * 60 * 1000

export interface SessionWarning {
  // When the sign-in ends (ms since the epoch).
  endsAt: number
  // False once renewing was refused: the sign-in has reached its maximum
  // length and cannot be extended.
  canExtend: boolean
  extend: () => void
}

// Keeps a working user signed in on every page, not only during a live call:
// without this the sign-in silently runs out and the next click throws away
// whatever was being typed. Someone who has gone idle is not renewed; they
// get a warning (returned here) they can answer, and are signed out as before
// if they do not.
export function useSessionGuard(): SessionWarning | null {
  const { session, refreshSession } = useAuth()
  const expiresAt = session?.expiresAt ?? null

  // Opening the page counts as activity.
  const lastActivityAt = useRef(0)
  useEffect(() => {
    lastActivityAt.current = Date.now()
  }, [])
  // The warning belongs to one sign-in token: a renewed one (a new expiry)
  // has none.
  const [warning, setWarning] = useState<{ endsAt: number; canExtend: boolean } | null>(null)
  const warningRef = useRef(warning)
  useEffect(() => {
    warningRef.current = warning
  }, [warning])

  const extend = useCallback(() => {
    if (expiresAt === null) {
      return
    }
    refreshSession().catch(() => {
      // Refused (the sign-in has reached its maximum length) or the server
      // could not be reached: say so rather than signing the user out early.
      setWarning({ endsAt: expiresAt, canExtend: false })
    })
  }, [expiresAt, refreshSession])

  useEffect(() => {
    const markActive = () => {
      lastActivityAt.current = Date.now()
      const shown = warningRef.current
      // Back at work while the warning is up: that is the answer.
      if (shown !== null && shown.canExtend && shown.endsAt === expiresAt) {
        warningRef.current = null
        extend()
      }
    }

    window.addEventListener('pointerdown', markActive, { passive: true })
    window.addEventListener('keydown', markActive, { passive: true })
    return () => {
      window.removeEventListener('pointerdown', markActive)
      window.removeEventListener('keydown', markActive)
    }
  }, [expiresAt, extend])

  useEffect(() => {
    if (expiresAt === null) {
      return
    }

    const timer = window.setTimeout(
      () => {
        if (Date.now() - lastActivityAt.current <= ACTIVE_WITHIN_MS) {
          extend()
        } else {
          setWarning({ endsAt: expiresAt, canExtend: true })
        }
      },
      Math.max(expiresAt - Date.now() - ACT_BEFORE_EXPIRY_MS, 0),
    )

    return () => {
      window.clearTimeout(timer)
    }
  }, [expiresAt, extend])

  if (warning === null || warning.endsAt !== expiresAt) {
    return null
  }
  return { ...warning, extend }
}
