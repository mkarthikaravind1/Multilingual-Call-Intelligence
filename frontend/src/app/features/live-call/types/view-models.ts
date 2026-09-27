export interface TranscriptTurnViewModel {
  utteranceId: string
  transcript: string
  speakerRole: string
  languages: string[]
  startTime: number
  endTime: number
  confidence: number | null
}

export interface ComplaintViewModel {
  category: string
  status: string
}

export interface SentimentViewModel {
  label: string
  confidence: number
  evidence: string
}

export interface QuestionSuggestionViewModel {
  question: string
  targetCategory: string
  priority: number
  reason: string
  source: string
  confidence: number | null
}

export interface CallMetadataViewModel {
  callId: string
  status: string
  startTime: number
  endTime: number | null
  utteranceCount: number
}

export interface CallAnalysisViewModel {
  complaints: ComplaintViewModel[]
  sentiment: SentimentViewModel | null
  questionSuggestion: QuestionSuggestionViewModel | null
}
