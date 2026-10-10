import { useSessionGuard } from '../auth/useSessionGuard'

function clockTime(at: number): string {
  return new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Shown above the page when the sign-in is about to end and was not renewed
// by itself (the user had gone idle, or it has reached its maximum length).
export function SessionExpiryNotice() {
  const warning = useSessionGuard()

  if (warning === null) {
    return null
  }

  return (
    <div className="inline-notice session-expiry-notice" role="alert">
      {warning.canExtend ? (
        <>
          <span>
            You will be signed out at {clockTime(warning.endsAt)} because you have not been
            active. Anything not saved will be lost.
          </span>
          <button type="button" className="button" onClick={warning.extend}>
            Stay signed in
          </button>
        </>
      ) : (
        <span>
          Your sign-in ends at {clockTime(warning.endsAt)} and could not be extended. Save your
          work now, then sign in again.
        </span>
      )}
    </div>
  )
}
