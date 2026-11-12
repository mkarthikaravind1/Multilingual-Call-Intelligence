import { describe, expect, it } from 'vitest'

import { complaintStatusTone, lineToneKey, sentimentTone } from './tone'

describe('complaintStatusTone', () => {
  it('maps known statuses case-insensitively', () => {
    expect(complaintStatusTone('RESOLVED')).toBe('success')
    expect(complaintStatusTone('Unresolved')).toBe('danger')
    expect(complaintStatusTone('probed')).toBe('warning')
  })

  it('defaults to neutral', () => {
    expect(complaintStatusTone('mystery')).toBe('neutral')
  })
})

describe('sentimentTone', () => {
  it('colours negative sentiment as danger', () => {
    expect(sentimentTone('frustrated')).toBe('danger')
    expect(sentimentTone('ESCALATING')).toBe('danger')
    expect(sentimentTone('positive')).toBe('success')
  })

  it('treats neutral and unknown as neutral', () => {
    expect(sentimentTone('NEUTRAL')).toBe('neutral')
    expect(sentimentTone('???')).toBe('neutral')
  })
})

describe('lineToneKey', () => {
  it('returns the lower-case tone for known labels', () => {
    expect(lineToneKey('FRUSTRATED')).toBe('frustrated')
  })

  it('returns null for missing or unknown labels', () => {
    expect(lineToneKey(null)).toBeNull()
    expect(lineToneKey(undefined)).toBeNull()
    expect(lineToneKey('angry')).toBeNull()
  })
})
