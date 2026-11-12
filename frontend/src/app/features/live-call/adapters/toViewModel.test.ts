import { describe, expect, it } from 'vitest'

import type {
  CallAnalysisResponseDto,
  CallSummaryDto,
  QuestionSuggestionDto,
  UtteranceDto,
} from '../types/dto'
import type { CallMetadataViewModel } from '../types/view-models'
import {
  formatAiStatus,
  formatCallDirection,
  formatCallPhase,
  formatCallerLabel,
  formatLoggingStatus,
  toCallAnalysisViewModel,
  toCallMetadataViewModel,
  toQuestionSuggestionViewModel,
  toTranscriptTurnViewModel,
} from './toViewModel'

// The tests spell out only the fields a case is about.
function dto<T>(partial: object): T {
  return partial as T
}

describe('toTranscriptTurnViewModel', () => {
  it('fills defaults for fields the analysis has not set yet', () => {
    const turn = toTranscriptTurnViewModel(
      dto<UtteranceDto>({
        utterance_id: 'u1',
        transcript: 'hello',
        speaker_role: 'CUSTOMER',
        languages: ['en'],
        start_time: 1,
        end_time: 2,
      }),
    )

    expect(turn).toMatchObject({
      utteranceId: 'u1',
      confidence: null,
      sentiment: null,
      complaintCategories: [],
      multiCategory: false,
    })
  })
})

describe('toCallMetadataViewModel', () => {
  it('maps optional fields to null and hold time to zero', () => {
    const call = toCallMetadataViewModel(
      dto<CallSummaryDto>({
        call_id: 'CALL-1',
        status: 'ACTIVE',
        start_time: 0,
        end_time: null,
        utterance_count: 3,
      }),
    )

    expect(call).toMatchObject({
      callId: 'CALL-1',
      phase: null,
      holdSeconds: 0,
      customerName: null,
      executiveName: null,
      direction: null,
    })
  })
})

describe('call formatters', () => {
  it('names the phase, or infers it from the status', () => {
    expect(formatCallPhase('on_hold', 'ACTIVE')).toBe('On hold')
    expect(formatCallPhase(null, 'COMPLETED')).toBe('Ended')
    expect(formatCallPhase(undefined, 'ACTIVE')).toBe('Connected')
  })

  it('names the direction', () => {
    expect(formatCallDirection('inbound')).toBe('Incoming')
    expect(formatCallDirection('outbound')).toBe('Outgoing')
    expect(formatCallDirection(null)).toBeNull()
  })

  it('names AI and logging statuses, passing unknown ones through', () => {
    expect(formatAiStatus('classifying_complaint')).toBe('Classifying complaint')
    expect(formatAiStatus('new_stage')).toBe('new_stage')
    expect(formatLoggingStatus('archive_complete')).toBe('Archive complete')
    expect(formatLoggingStatus('other')).toBe('other')
  })

  it('labels the caller with as much as is known', () => {
    const base = dto<CallMetadataViewModel>({ customerName: null, vehicleRegistration: null })

    expect(formatCallerLabel(base)).toBe('Unknown caller')
    expect(formatCallerLabel({ ...base, customerName: 'Asha' })).toBe('Asha')
    expect(formatCallerLabel({ ...base, customerName: 'Asha', vehicleRegistration: 'TN01AB1234' })).toBe(
      'Asha(TN01AB1234)',
    )
  })
})

describe('toQuestionSuggestionViewModel', () => {
  it('defaults the language to English and optional fields to null', () => {
    const suggestion = toQuestionSuggestionViewModel(
      dto<QuestionSuggestionDto>({ question: 'When did it start?', target_category: 'COST' }),
    )

    expect(suggestion).toMatchObject({
      question: 'When did it start?',
      targetCategory: 'COST',
      language: 'en',
      confidence: null,
      questionEnglish: null,
    })
  })
})

describe('toCallAnalysisViewModel', () => {
  const suggestion = dto<QuestionSuggestionDto>({ question: 'Q1', target_category: 'COST' })

  function analysis(extra: object) {
    return dto<CallAnalysisResponseDto>({ coverage: { complaints: [] }, ...extra })
  }

  it('uses the single question when an older server sends no list', () => {
    const view = toCallAnalysisViewModel(analysis({ question_suggestion: suggestion }))

    expect(view.questionSuggestions.map((q) => q.question)).toEqual(['Q1'])
    expect(view.questionSuggestion?.question).toBe('Q1')
  })

  it('prefers the list when the server sends one', () => {
    const view = toCallAnalysisViewModel(
      analysis({
        question_suggestion: suggestion,
        question_suggestions: [suggestion, { ...suggestion, question: 'Q2' }],
      }),
    )

    expect(view.questionSuggestions.map((q) => q.question)).toEqual(['Q1', 'Q2'])
  })

  it('leaves absent parts null or empty', () => {
    const view = toCallAnalysisViewModel(analysis({}))

    expect(view).toMatchObject({
      sentiment: null,
      questionSuggestion: null,
      questionSuggestions: [],
      serviceEstimate: null,
      escalation: null,
      postCallSummary: null,
      alerts: [],
      loggingStatuses: [],
      aiStatus: null,
    })
  })

  it('maps alerts to camelCase', () => {
    const view = toCallAnalysisViewModel(
      analysis({
        alerts: [{ alert_type: 'poor_audio', subject: 'audio', message: 'Noisy', cleared_at: null }],
      }),
    )

    expect(view.alerts).toEqual([
      { alertType: 'poor_audio', subject: 'audio', message: 'Noisy', clearedAt: null },
    ])
  })
})
