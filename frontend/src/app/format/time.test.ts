import { describe, expect, it } from 'vitest'

import { formatCallDuration, formatElapsedSeconds, formatRecordTimestamp } from './time'

describe('formatElapsedSeconds', () => {
  it('formats minutes and zero-padded seconds', () => {
    expect(formatElapsedSeconds(0)).toBe('0:00')
    expect(formatElapsedSeconds(65.9)).toBe('1:05')
    expect(formatElapsedSeconds(3600)).toBe('60:00')
  })

  it('falls back to 0:00 for invalid values', () => {
    expect(formatElapsedSeconds(-1)).toBe('0:00')
    expect(formatElapsedSeconds(Number.NaN)).toBe('0:00')
    expect(formatElapsedSeconds(Infinity)).toBe('0:00')
  })
})

describe('formatRecordTimestamp', () => {
  it('shows a dash when there is no wall-clock time', () => {
    expect(formatRecordTimestamp(0)).toBe('—')
    expect(formatRecordTimestamp(-5)).toBe('—')
    expect(formatRecordTimestamp(Number.NaN)).toBe('—')
  })

  it('formats real epoch seconds', () => {
    expect(formatRecordTimestamp(1_700_000_000)).toMatch(/2023/)
  })
})

describe('formatCallDuration', () => {
  it('reports in progress while the call is open', () => {
    expect(formatCallDuration(100, null)).toBe('In progress')
  })

  it('uses the difference, not wall-clock values', () => {
    expect(formatCallDuration(0, 125)).toBe('2:05')
    expect(formatCallDuration(1000, 1060)).toBe('1:00')
  })
})
