import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/errors'
import { LoginForm } from './LoginForm'

const auth = vi.hoisted(() => ({
  login: vi.fn<(email: string, password: string) => Promise<void>>(),
  isLoading: false,
  statusMessage: null as string | null,
}))
vi.mock('../../auth/useAuth', () => ({ useAuth: () => auth }))

function Landed() {
  return <p>Landed on {useLocation().pathname}</p>
}

function renderForm(initialEntry: string | { pathname: string; state: unknown } = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<LoginForm />} />
        <Route path="*" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
}

async function fill(email: string, password: string) {
  const user = userEvent.setup()
  if (email) await user.type(screen.getByLabelText('Email'), email)
  if (password) await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

beforeEach(() => {
  auth.login.mockReset().mockResolvedValue(undefined)
  auth.isLoading = false
  auth.statusMessage = null
})

describe('LoginForm', () => {
  it('rejects an invalid email without calling the server', async () => {
    renderForm()

    await fill('not-an-email', 'pw')

    expect(screen.getByRole('alert')).toHaveTextContent('valid email')
    expect(auth.login).not.toHaveBeenCalled()
  })

  it('requires a password', async () => {
    renderForm()

    await fill('a@b.co', '')

    expect(screen.getByRole('alert')).toHaveTextContent('Password is required')
    expect(auth.login).not.toHaveBeenCalled()
  })

  it('signs in with the trimmed email and goes to the dashboard', async () => {
    renderForm()

    await fill('  a@b.co ', 'secret')

    expect(auth.login).toHaveBeenCalledWith('a@b.co', 'secret')
    expect(await screen.findByText('Landed on /dashboard')).toBeInTheDocument()
  })

  it('returns to the page the user was sent from', async () => {
    renderForm({ pathname: '/login', state: { from: '/complaints' } })

    await fill('a@b.co', 'secret')

    expect(await screen.findByText('Landed on /complaints')).toBeInTheDocument()
  })

  it('shows the server message when sign-in is refused', async () => {
    auth.login.mockRejectedValue(new ApiError(401, 'Incorrect email or password.'))
    renderForm()

    await fill('a@b.co', 'wrong')

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
    expect(screen.queryByText(/Landed on/)).toBeNull()
  })

  it('shows a generic message for unexpected failures', async () => {
    auth.login.mockRejectedValue(new Error('x'))
    renderForm()

    await fill('a@b.co', 'secret')

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to sign in')
  })

  it('disables the button while signing in', () => {
    auth.isLoading = true
    renderForm()

    expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled()
  })
})
