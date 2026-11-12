import { beforeEach, describe, expect, it } from 'vitest'

import {
  AUTH_SESSION_KEY,
  clearSessionStorage,
  decodeJwtClaims,
  readSessionToken,
  writeSessionToken,
} from './session'

// A JWT is three base64url parts; only the middle one is read.
function jwt(claims: object) {
  const payload = btoa(JSON.stringify(claims))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
  return `header.${payload}.signature`
}

beforeEach(() => {
  sessionStorage.clear()
})

describe('decodeJwtClaims', () => {
  it('reads the claims, including unpadded base64url payloads', () => {
    expect(decodeJwtClaims(jwt({ role: 'ADMIN', exp: 123 }))).toEqual({ role: 'ADMIN', exp: 123 })
    // "?>" encodes to characters that differ between base64 and base64url.
    expect(decodeJwtClaims(jwt({ note: '??>>' }))).toEqual({ note: '??>>' })
  })

  it('returns no claims for a malformed token', () => {
    expect(decodeJwtClaims('nope')).toEqual({})
    expect(decodeJwtClaims('a.!!!.c')).toEqual({})
    expect(decodeJwtClaims('a.bm90LWpzb24.c')).toEqual({})
  })
})

describe('session token storage', () => {
  it('round-trips a token and clears it', () => {
    expect(readSessionToken()).toBeNull()

    writeSessionToken('abc')
    expect(readSessionToken()).toBe('abc')

    clearSessionStorage()
    expect(readSessionToken()).toBeNull()
  })

  it('discards a corrupt entry instead of throwing', () => {
    sessionStorage.setItem(AUTH_SESSION_KEY, '{not json')

    expect(readSessionToken()).toBeNull()
    expect(sessionStorage.getItem(AUTH_SESSION_KEY)).toBeNull()
  })

  it('ignores an entry without a string token', () => {
    sessionStorage.setItem(AUTH_SESSION_KEY, JSON.stringify({ accessToken: 5 }))

    expect(readSessionToken()).toBeNull()
  })
})
