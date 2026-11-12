import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/errors'
import { AuthProvider } from './AuthContext'
import { useAuth } from './useAuth'

const mocks = vi.hoisted(() => ({
  handlers: {} as { onUnauthorized?: () => void; onForbidden?: () => void },
  session: null as null | { accessToken: string; role: string; expiresAt: null; provisional: boolean },
  authService: {
    getSession: vi.fn(),
    isAuthenticated: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  },
}))

vi.mock('../api/client', () => ({
  apiClient: {
    setErrorHandlers: (handlers: typeof mocks.handlers) => {
      mocks.handlers = handlers
    },
  },
}))
vi.mock('./AuthService', () => ({ authService: mocks.authService }))

const SESSION = { accessToken: 't', role: 'ICR', expiresAt: null, provisional: true }

function Probe() {
  const auth = useAuth()
  return (
    <div>
      <p>{auth.isAuthenticated ? 'signed in' : 'signed out'}</p>
      <p>message: {auth.statusMessage ?? 'none'}</p>
      <p>{auth.isLoading ? 'loading' : 'idle'}</p>
      <button type="button" onClick={() => auth.login('a@b.co', 'pw').catch(() => {})}>
        login
      </button>
      <button type="button" onClick={auth.logout}>
        logout
      </button>
    </div>
  )
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  )
}

beforeEach(() => {
  mocks.session = null
  mocks.authService.getSession.mockReset().mockImplementation(() => mocks.session)
  mocks.authService.isAuthenticated.mockReset().mockImplementation(() => mocks.session !== null)
  mocks.authService.login.mockReset().mockImplementation(async () => {
    mocks.session = SESSION
    return SESSION
  })
  mocks.authService.logout.mockReset().mockImplementation(() => {
    mocks.session = null
  })
})

describe('AuthProvider', () => {
  it('starts signed out and signs in', async () => {
    renderProvider()
    expect(screen.getByText('signed out')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'login' }))

    expect(await screen.findByText('signed in')).toBeInTheDocument()
    expect(screen.getByText('idle')).toBeInTheDocument()
  })

  it('starts signed in when a session was restored', () => {
    mocks.session = SESSION

    renderProvider()

    expect(screen.getByText('signed in')).toBeInTheDocument()
  })

  it('shows the server message when login is refused', async () => {
    mocks.authService.login.mockRejectedValue(new ApiError(401, 'Incorrect email or password.'))
    renderProvider()

    await userEvent.click(screen.getByRole('button', { name: 'login' }))

    expect(await screen.findByText('message: Incorrect email or password.')).toBeInTheDocument()
    expect(screen.getByText('signed out')).toBeInTheDocument()
  })

  it('signs the user out with a message when the API says 401', () => {
    mocks.session = SESSION
    renderProvider()

    act(() => mocks.handlers.onUnauthorized?.())

    expect(mocks.authService.logout).toHaveBeenCalled()
    expect(screen.getByText('signed out')).toBeInTheDocument()
    expect(screen.getByText('message: Your session has expired. Please sign in again.')).toBeInTheDocument()
  })

  it('only warns on 403 and stays signed in', () => {
    mocks.session = SESSION
    renderProvider()

    act(() => mocks.handlers.onForbidden?.())

    expect(screen.getByText('signed in')).toBeInTheDocument()
    expect(screen.getByText(/do not have permission/)).toBeInTheDocument()
  })

  it('clears the message on a deliberate logout', async () => {
    mocks.session = SESSION
    renderProvider()
    act(() => mocks.handlers.onForbidden?.())

    await userEvent.click(screen.getByRole('button', { name: 'logout' }))

    expect(screen.getByText('signed out')).toBeInTheDocument()
    expect(screen.getByText('message: none')).toBeInTheDocument()
  })
})
