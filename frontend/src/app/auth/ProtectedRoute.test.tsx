import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ProtectedRoute } from './ProtectedRoute'

const auth = vi.hoisted(() => ({ isAuthenticated: false }))
vi.mock('./useAuth', () => ({ useAuth: () => auth }))

function LoginProbe() {
  const location = useLocation()
  return <p>Login from {(location.state as { from?: string } | null)?.from}</p>
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<LoginProbe />} />
        <Route
          path="/calls"
          element={
            <ProtectedRoute>
              <p>Secret calls</p>
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  auth.isAuthenticated = false
})

describe('ProtectedRoute', () => {
  it('sends a signed-out user to login, remembering where they were going', () => {
    renderAt('/calls?status=active')

    expect(screen.getByText('Login from /calls?status=active')).toBeInTheDocument()
    expect(screen.queryByText('Secret calls')).toBeNull()
  })

  it('shows the page to a signed-in user', () => {
    auth.isAuthenticated = true
    renderAt('/calls')

    expect(screen.getByText('Secret calls')).toBeInTheDocument()
  })
})
