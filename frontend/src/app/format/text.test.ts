import { describe, expect, it } from 'vitest'

import { humanizeLabel } from './text'

describe('humanizeLabel', () => {
  it('turns enum values into readable labels', () => {
    expect(humanizeLabel('pending_review')).toBe('Pending review')
    expect(humanizeLabel('NOT_RAISED')).toBe('Not raised')
    expect(humanizeLabel('turn-around')).toBe('Turn around')
  })

  it('trims and handles empty input', () => {
    expect(humanizeLabel('  _open_ ')).toBe('Open')
    expect(humanizeLabel('')).toBe('')
  })
})
