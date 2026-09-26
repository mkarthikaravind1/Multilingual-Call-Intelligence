import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/errors'
import { useAuth } from '../../auth/useAuth'

export function LoginForm() {
  const navigate = useNavigate()
  const { login, isLoading, statusMessage } = useAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const trimmedEmail = email.trim()
    if (!trimmedEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setFieldError('Please enter a valid email address.')
      return
    }

    if (!password.trim()) {
      setFieldError('Password is required.')
      return
    }

    setFieldError(null)

    try {
      await login(trimmedEmail, password)
      navigate('/dashboard', { replace: true })
    } catch (error) {
      if (error instanceof ApiError) {
        setFieldError(error.message)
      } else {
        setFieldError('Unable to sign in. Please try again.')
      }
    }
  }

  return (
    <form className="auth-form" onSubmit={handleSubmit} noValidate>
      <div className="auth-form__field">
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="email"
          placeholder="you@dealer.com"
          aria-invalid={Boolean(fieldError || statusMessage)}
        />
      </div>

      <div className="auth-form__field">
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          placeholder="Enter your password"
          aria-invalid={Boolean(fieldError || statusMessage)}
        />
      </div>

      {(fieldError || statusMessage) && (
        <div className="auth-form__error" role="alert">
          {fieldError ?? statusMessage}
        </div>
      )}

      <button type="submit" className="auth-form__submit" disabled={isLoading}>
        {isLoading ? 'Signing in…' : 'Sign in'}
      </button>
    </form>
  )
}
