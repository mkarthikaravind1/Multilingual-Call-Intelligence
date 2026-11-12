import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthService } from './AuthService'
import { AUTH_SESSION_KEY, readSessionToken } from './session'

const api = vi.hoisted(() => ({
  post: vi.fn(),
  request: vi.fn(),
  setAccessToken: vi.fn(),
}))
vi.mock('../api/client', () => ({ apiClient: api }))

function jwt(claims: object) {
  return `h.${btoa(JSON.stringify(claims)).replace(/=+$/, '')}.s`
}

const inAnHour = () => Math.floor(Date.now() / 1000) + 3600
const anHourAgo = () => Math.floor(Date.now() / 1000) - 3600

beforeEach(() => {
  sessionStorage.clear()
  api.post.mockReset()
  api.request.mockReset()
  api.setAccessToken.mockReset()
})

describe('AuthService.login', () => {
  it('starts a session from the token the server returns', async () => {
    const token = jwt({ role: 'SUPERVISOR', exp: inAnHour() })
    api.post.mockResolvedValue({ access_token: token })
    const service = new AuthService()

    const session = await service.login('a@b.co', 'pw')

    expect(api.post).toHaveBeenCalledWith('/api/v1/auth/login', { email: 'a@b.co', password: 'pw' })
    expect(session.role).toBe('SUPERVISOR')
    expect(service.isAuthenticated()).toBe(true)
    expect(service.hasRole('SUPERVISOR')).toBe(true)
    expect(service.getAccessToken()).toBe(token)
    expect(api.setAccessToken).toHaveBeenLastCalledWith(token)
    expect(readSessionToken()).toBe(token)
  })

  it('treats an unknown role as no role', async () => {
    api.post.mockResolvedValue({ access_token: jwt({ role: 'ROOT', exp: inAnHour() }) })
    const service = new AuthService()

    await service.login('a@b.co', 'pw')

    expect(service.getRole()).toBeNull()
  })

  it('stays signed out when the server refuses', async () => {
    api.post.mockRejectedValue(new Error('no'))
    const service = new AuthService()

    await expect(service.login('a@b.co', 'bad')).rejects.toThrow('no')

    expect(service.isAuthenticated()).toBe(false)
  })
})

describe('AuthService.restoreSession', () => {
  it('restores a valid stored token on construction', () => {
    const token = jwt({ role: 'ADMIN', exp: inAnHour() })
    sessionStorage.setItem(AUTH_SESSION_KEY, JSON.stringify({ accessToken: token }))

    const service = new AuthService()

    expect(service.getRole()).toBe('ADMIN')
    expect(api.setAccessToken).toHaveBeenCalledWith(token)
  })

  it('drops an expired stored token', () => {
    const token = jwt({ role: 'ADMIN', exp: anHourAgo() })
    sessionStorage.setItem(AUTH_SESSION_KEY, JSON.stringify({ accessToken: token }))

    const service = new AuthService()

    expect(service.isAuthenticated()).toBe(false)
    expect(sessionStorage.getItem(AUTH_SESSION_KEY)).toBeNull()
  })
})

describe('AuthService.isAuthenticated', () => {
  it('is false once the token has expired', async () => {
    vi.useFakeTimers()
    try {
      api.post.mockResolvedValue({ access_token: jwt({ exp: Math.floor(Date.now() / 1000) + 60 }) })
      const service = new AuthService()
      await service.login('a@b.co', 'pw')
      expect(service.isAuthenticated()).toBe(true)

      vi.advanceTimersByTime(61_000)

      expect(service.isAuthenticated()).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('AuthService.logout', () => {
  it('clears the session, the client token and storage', async () => {
    api.post.mockResolvedValue({ access_token: jwt({ role: 'ICR', exp: inAnHour() }) })
    const service = new AuthService()
    await service.login('a@b.co', 'pw')

    service.logout()

    expect(service.getSession()).toBeNull()
    expect(api.setAccessToken).toHaveBeenLastCalledWith(null)
    expect(readSessionToken()).toBeNull()
  })
})

describe('AuthService.refresh', () => {
  it('shares one request between callers and replaces the token', async () => {
    const fresh = jwt({ role: 'ICR', exp: inAnHour() })
    api.request.mockResolvedValue({ access_token: fresh })
    const service = new AuthService()

    const [a, b] = await Promise.all([service.refresh(), service.refresh()])

    expect(api.request).toHaveBeenCalledTimes(1)
    expect(a).toBe(b)
    expect(service.getAccessToken()).toBe(fresh)
    // quiet: a refused renewal must not sign the user out.
    expect(api.request.mock.calls[0][2]).toBe(true)
  })

  it('keeps the current session when renewal is refused, and can retry', async () => {
    const current = jwt({ role: 'ICR', exp: inAnHour() })
    api.post.mockResolvedValue({ access_token: current })
    const service = new AuthService()
    await service.login('a@b.co', 'pw')
    api.request.mockRejectedValueOnce(new Error('max length'))

    await expect(service.refresh()).rejects.toThrow('max length')
    expect(service.getAccessToken()).toBe(current)

    api.request.mockResolvedValueOnce({ access_token: jwt({ role: 'ICR', exp: inAnHour() }) })
    await expect(service.refresh()).resolves.toBeDefined()
    expect(api.request).toHaveBeenCalledTimes(2)
  })
})
