import type {
  CallAnalysisResponseDto,
  CallResponseDto,
  ComplaintDto,
  QuestionSuggestionDto,
  SentimentDto,
  UtteranceDto,
} from '../types/dto'

import type {
  CallAnalysisViewModel,
  CallMetadataViewModel,
  ComplaintViewModel,
  QuestionSuggestionViewModel,
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
  }
}