import { describe, expect, it } from 'vitest'

import type { EscalationDto } from '../types/dto'
import { toEscalationViewModel } from './toEscalationViewModel'

describe('toEscalationViewModel', () => {
  it('maps the escalation and its signals to camelCase', () => {
    const view = toEscalationViewModel({
      call_id: 'CALL-1',
      level: 'high',
      status: 'acknowledged',
      signals: [
        { signal_type: 'threat', level: 'high', description: 'Legal threat', evidence: 'I will sue' },
      ],
      first_detected_at: 10,
      updated_at: 20,
      acknowledged_by: 'sup@example.com',
      acknowledged_at: 15,
      resolved_by: null,
      resolved_at: null,
      resolution_note: null,
    } as unknown as EscalationDto)

    expect(view).toEqual({
      callId: 'CALL-1',
      level: 'high',
      status: 'acknowledged',
      signals: [
        { type: 'threat', level: 'high', description: 'Legal threat', evidence: 'I will sue' },
      ],
      firstDetectedAt: 10,
      updatedAt: 20,
      acknowledgedBy: 'sup@example.com',
      acknowledgedAt: 15,
      resolvedBy: null,
      resolvedAt: null,
      resolutionNote: null,
    })
  })
})
