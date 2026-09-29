import type { EscalationDto } from '../types/dto'
import type { EscalationViewModel } from '../types/view-models'

export function toEscalationViewModel(escalation: EscalationDto): EscalationViewModel {
  return {
    callId: escalation.call_id,
    level: escalation.level,
    status: escalation.status,
    signals: escalation.signals.map((signal) => ({
      type: signal.signal_type,
      level: signal.level,
      description: signal.description,
      evidence: signal.evidence,
    })),
    firstDetectedAt: escalation.first_detected_at,
    updatedAt: escalation.updated_at,
    acknowledgedBy: escalation.acknowledged_by,
    acknowledgedAt: escalation.acknowledged_at,
    resolvedBy: escalation.resolved_by,
    resolvedAt: escalation.resolved_at,
    resolutionNote: escalation.resolution_note,
  }
}
