import type {
  CallAnalysisResponseDto,
  CallResponseDto,
  ComplaintDto,
  ComplaintSummaryDto,
  PostCallSummaryDto,
  QuestionSuggestionDto,
  ServiceEstimateDto,
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
  }
}

export function toCallMetadataViewModel(
  call: CallResponseDto,
): CallMetadataViewModel {
  return {
    callId: call.call_id,
    status: call.status,
    startTime: call.start_time,
    endTime: call.end_time,
    utteranceCount: call.utterance_count,
  }
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
  }
}

export function toServiceEstimateViewModel(
  estimate: ServiceEstimateDto,
): ServiceEstimateViewModel {
  return {
    serviceName: estimate.service_name,
    currency: estimate.currency,
    parts: estimate.parts.map((part) => ({
      name: part.name,
      quantity: part.quantity,
      unitPrice: part.unit_price,
      totalPrice: part.total_price,
    })),
    labour: {
      hours: estimate.labour.hours,
      hourlyRate: estimate.labour.hourly_rate,
      totalCost: estimate.labour.total_cost,
    },
    estimatedDurationHours: estimate.estimated_duration_hours,
    partsCost: estimate.parts_cost,
    labourCost: estimate.labour_cost,
    estimatedCost: estimate.estimated_cost,
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

    sentiment: toSentimentViewModel(
      analysis.sentiment,
    ),

    questionSuggestion:
      analysis.question_suggestion
        ? toQuestionSuggestionViewModel(
            analysis.question_suggestion,
          )
        : null,

    serviceEstimate: analysis.service_estimate
      ? toServiceEstimateViewModel(analysis.service_estimate)
      : null,

    postCallSummary: analysis.post_call_summary
      ? toPostCallSummaryViewModel(analysis.post_call_summary)
      : null,
  }
}