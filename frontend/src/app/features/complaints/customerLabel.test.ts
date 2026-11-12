import { describe, expect, it } from 'vitest'

import { customerLabel } from './customerLabel'
import type { ComplaintDto } from './types/dto'

const complaint = (fields: object) => fields as ComplaintDto

describe('customerLabel', () => {
  it('is null when the customer is unknown', () => {
    expect(customerLabel(complaint({ customer_name: null }))).toBeNull()
  })

  it('adds the vehicle number when known', () => {
    expect(customerLabel(complaint({ customer_name: 'Asha' }))).toBe('Asha')
    expect(
      customerLabel(complaint({ customer_name: 'Asha', vehicle_registration: 'TN01AB1234' })),
    ).toBe('Asha(TN01AB1234)')
  })
})
