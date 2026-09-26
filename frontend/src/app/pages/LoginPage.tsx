import { Navigate, useLocation } from 'react-router-dom'

import { LoginForm } from '../features/auth/LoginForm'
import { useAuth } from '../auth/useAuth'

export function LoginPage() {
  const { isAuthenticated } = useAuth()
  const location = useLocation()

  if (isAuthenticated) {
    const redirectTarget = typeof location.state === 'object' && location.state && 'from' in location.state
      ? String((location.state as { from?: string }).from ?? '/dashboard')
      : '/dashboard'

    return <Navigate to={redirectTarget} replace />
  }

  return (
    <main className="login-page">
      <div className="login-card">
        <p className="eyebrow">Welcome</p>
        <h1>Multilingual Call Intelligence</h1>
        <p className="login-card__text">
          Enterprise automotive CX surface for live call monitoring, analysis, and improvement workflows.
        </p>

        <LoginForm />
      </div>
    </main>
  )
}
