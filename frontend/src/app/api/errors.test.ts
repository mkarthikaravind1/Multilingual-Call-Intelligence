import { describe, expect, it } from 'vitest'

import { ApiError, getErrorMessage, toUserErrorMessage } from './errors'

describe('getErrorMessage', () => {
  it('reads a string detail', () => {
    expect(getErrorMessage({ detail: 'Nope' }, 'fb')).toBe('Nope')
  })

  it('reads the first validation message from a detail list', () => {
    expect(getErrorMessage({ detail: [{ msg: 'field required' }] }, 'fb')).toBe('field required')
  })

  it('falls back to message, then the fallback', () => {
    expect(getErrorMessage({ message: 'm' }, 'fb')).toBe('m')
    expect(getErrorMessage({ detail: [] }, 'fb')).toBe('fb')
    expect(getErrorMessage(null, 'fb')).toBe('fb')
    expect(getErrorMessage('text', 'fb')).toBe('fb')
  })
})

describe('toUserErrorMessage', () => {
  it('uses the message of ApiError and Error instances', () => {
    expect(toUserErrorMessage(new ApiError(404, 'Not found'), 'fb')).toBe('Not found')
    expect(toUserErrorMessage(new Error('boom'), 'fb')).toBe('boom')
  })

  it('reads plain payload objects', () => {
    expect(toUserErrorMessage({ detail: 'bad' }, 'fb')).toBe('bad')
  })
})

describe('ApiError', () => {
  it('keeps status and payload', () => {
    const error = new ApiError(422, 'Invalid', { a: 1 })
    expect(error.status).toBe(422)
    expect(error.detail).toBe('Invalid')
    expect(error.payload).toEqual({ a: 1 })
    expect(error.name).toBe('ApiError')
  })
})
