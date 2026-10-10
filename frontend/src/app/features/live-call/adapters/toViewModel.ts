import { toEscalationViewModel } from '../../escalation/adapters/toEscalationViewModel'

import type {
  CallAnalysisResponseDto,
  CallDirection,
  CallSummaryDto,
  ComplaintDto,
  ComplaintSummaryDto,
  PostCallSummaryDto,
  QuestionSuggestionDto,
  ServiceEstimateDto,
  ServiceLineDto,
  SentimentDto,
  UtteranceDto,
} from '../types/dto'

import type {
  CallAnalysisViewModel,
  CallMetadataViewModel,
  ComplaintSummaryViewModel,
  ComplaintViewModel,
  PostCallSummaryViewModel,
  QuestionSuggestionViewModel,
  ServiceEstimateViewModel,
  ServiceLineViewModel,
  SentimentViewModel,
  TranscriptTurnViewModel,
} from '../types/view-models'

export function toTranscriptTurnViewModel(
  utterance: UtteranceDto,
): TranscriptTurnViewModel {
  return {
    utteranceId: utterance.utterance_id,
    transcript: utterance.transcript,
    speakerRole: utterance.speaker_role,
    languages: utterance.languages,
    startTime: utterance.start_time,
    endTime: utterance.end_time,
    confidence: utterance.confidence ?? null,
    sentiment: utterance.sentiment ?? null,
  }
}

export function toCallMetadataViewModel(
  call: CallSummaryDto,
): CallMetadataViewModel {
  return {
    callId: call.call_id,
    status: call.status,
    startTime: call.start_time,
    endTime: call.end_time,
    utteranceCount: call.utterance_count,
    escalationLevel: call.escalation_level ?? null,
    escalationStatus: call.escalation_status ?? null,
    callerNumber: call.caller_number ?? null,
    customerName: call.customer_name ?? null,
    vehicleRegistration: call.vehicle_registration ?? null,
    complaintsResolvedAt: call.complaints_resolved_at ?? null,
    direction: call.direction ?? null,
    locationId: call.location_id ?? null,
    locationName: call.location_name ?? null,
    executiveUserId: call.executive_user_id ?? null,
    executiveName: call.executive_name ?? null,
  }
}

export function formatCallDirection(direction: CallDirection | null): string | null {
  if (direction === 'inbound') return 'Incoming'
  if (direction === 'outbound') return 'Outgoing'
  return null
}

// "Customer Name(Vehicle Number)", or as much of it as is known.
export function formatCallerLabel(call: CallMetadataViewModel): string {
  if (!call.customerName) {
    return 'Unknown caller'
  }
  return call.vehicleRegistration
    ? `${call.customerName}(${call.vehicleRegistration})`
    : call.customerName
}

export function toComplaintViewModel(
  complaint: ComplaintDto,
): ComplaintViewModel {
  return {
    category: complaint.category,
    status: complaint.status,
  }
}

export function toSentimentViewModel(
  sentiment: SentimentDto,
): SentimentViewModel {
  return {
    label: sentiment.label,
    confidence: sentiment.confidence,
    evidence: sentiment.evidence,
  }
}

export function toQuestionSuggestionViewModel(
  suggestion: QuestionSuggestionDto,
): QuestionSuggestionViewModel {
  return {
    question: suggestion.question,
    targetCategory:
      suggestion.target_category,
    priority: suggestion.priority,
    reason: suggestion.reason,
    source: suggestion.source,
    confidence: suggestion.confidence ?? null,
    language: suggestion.language ?? 'en',
    questionEnglish: suggestion.question_en ?? null,
  }
}

export function toServiceEstimateViewModel(
  estimate: ServiceEstimateDto,
): ServiceEstimateViewModel {
  return {
    currency: estimate.currency,
    services: estimate.services.map(toServiceLineViewModel),
    estimatedDurationHours: estimate.estimated_duration_hours,
    partsCost: estimate.parts_cost,
    labourCost: estimate.labour_cost,
    estimatedCost: estimate.estimated_cost,
    gstAmount: estimate.gst_amount,
    totalCost: estimate.total_cost,
    vehicleModel: estimate.vehicle_model,
    approximate: estimate.approximate,
  }
}

function toServiceLineViewModel(line: ServiceLineDto): ServiceLineViewModel {
  return {
    serviceName: line.service_name,
    currency: line.currency,
    parts: line.parts.map((part) => ({
      name: part.name,
      quantity: part.quantity,
      unitPrice: part.unit_price,
      totalPrice: part.total_price,
      gstPercent: part.gst_percent,
    })),
    labour: {
      hours: line.labour.hours,
      hourlyRate: line.labour.hourly_rate,
      totalCost: line.labour.total_cost,
      gstPercent: line.labour.gst_percent,
    },
    estimatedDurationHours: line.estimated_duration_hours,
    partsCost: line.parts_cost,
    labourCost: line.labour_cost,
    estimatedCost: line.estimated_cost,
    gstAmount: line.gst_amount,
    totalCost: line.total_cost,
    pricedForModel: line.priced_for_model,
    approximate: line.approximate,
  }
}

export function toComplaintSummaryViewModel(
  complaint: ComplaintSummaryDto,
): ComplaintSummaryViewModel {
  return {
    category: complaint.category,
    description: complaint.description,
    status: complaint.status,
    evidence: complaint.evidence,
    confidence: complaint.confidence ?? null,
  }
}

export function toPostCallSummaryViewModel(
  summary: PostCallSummaryDto,
): PostCallSummaryViewModel {
  return {
    callId: summary.call_id,
    overallSummary: summary.overall_summary,
    languages: summary.languages,
    sentiment: toSentimentViewModel(summary.sentiment),
    complaints: summary.complaints.map(toComplaintSummaryViewModel),
    unresolvedIssues: summary.unresolved_issues,
    actionsPromised: summary.actions_promised,
    followUpRequired: summary.follow_up_required,
    customerSummary: summary.customer_summary,
    serviceEstimate: summary.service_estimate
      ? toServiceEstimateViewModel(summary.service_estimate)
      : null,
  }
}

export function toCallAnalysisViewModel(
  analysis: CallAnalysisResponseDto,
): CallAnalysisViewModel {
  return {
    complaints:
      analysis.coverage.complaints.map(
        toComplaintViewModel,
      ),

    sentiment: analysis.sentiment
      ? toSentimentViewModel(analysis.sentiment)
      : null,

    questionSuggestion:
      analysis.question_suggestion
        ? toQuestionSuggestionViewModel(
            analysis.question_suggestion,
          )
        : null,

    serviceEstimate: analysis.service_estimate
      ? toServiceEstimateViewModel(analysis.service_estimate)
      : null,

    escalation: analysis.escalation
      ? toEscalationViewModel(analysis.escalation)
      : null,

    postCallSummary: analysis.post_call_summary
      ? toPostCallSummaryViewModel(analysis.post_call_summary)
      : null,
  }
}