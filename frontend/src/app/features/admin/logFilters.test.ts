import { describe, expect, it } from 'vitest'

import { localMidnight, withFilter } from './logFilters'

describe('localMidnight', () => {
  it('returns epoch seconds for local midnight of the day', () => {
    expect(localMidnight('2026-10-02')).toBe(new Date(2026, 9, 2).getTime() / 1000)
  })

  it('adds days, rolling over month ends', () => {
    expect(localMidnight('2026-10-31', 1)).toBe(new Date(2026, 10, 1).getTime() / 1000)
  })

  it('returns undefined for an empty or malformed day', () => {
    expect(localMidnight('')).toBeUndefined()
    expect(localMidnight('2026-10')).toBeUndefined()
    expect(localMidnight('abc')).toBeUndefined()
  })
})

describe('withFilter', () => {
  it('sets, replaces and removes filters without touching the original', () => {
    const current = new URLSearchParams('user=a&level=high')

    const next = withFilter(current, { user: 'b', level: '' })

    expect(next.toString()).toBe('user=b')
    expect(current.toString()).toBe('user=a&level=high')
  })

  it('goes back to the first page on any change', () => {
    const next = withFilter(new URLSearchParams('offset=100&user=a'), { user: 'b' })

    expect(next.has('offset')).toBe(false)
  })

  it('keeps the offset when the change is to the offset itself', () => {
    const next = withFilter(new URLSearchParams('user=a'), { offset: '50' })

    expect(next.get('offset')).toBe('50')
  })

  it('supports a custom offset parameter', () => {
    const next = withFilter(new URLSearchParams('page_offset=9'), { q: 'x' }, 'page_offset')

    expect(next.toString()).toBe('q=x')
  })
})
