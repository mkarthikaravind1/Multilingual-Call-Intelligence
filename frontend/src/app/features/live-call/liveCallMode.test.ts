import { describe, expect, it } from 'vitest'

import { isCallDetailsView } from './liveCallMode'

describe('isCallDetailsView', () => {
  it('is true for a call opened from a list (call_id alone)', () => {
    expect(isCallDetailsView(new URLSearchParams('call_id=CALL-1'))).toBe(true)
  })

  it('is false for a call started on the page', () => {
    expect(isCallDetailsView(new URLSearchParams('call_id=CALL-1&live=1'))).toBe(false)
  })

  it('is false without a usable call id', () => {
    expect(isCallDetailsView(new URLSearchParams(''))).toBe(false)
    expect(isCallDetailsView(new URLSearchParams('call_id=%20'))).toBe(false)
  })
})
