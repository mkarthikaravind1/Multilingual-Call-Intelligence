import { apiClient } from '../../../api/client'

import type {
  ActiveImprovementDto,
  CallObservationDto,
  LearningCandidateDto,
  LearningEvidenceDto,
  LearningFeedbackDto,
  LearningFeedbackRequestDto,
  LearningPatternDto,
} from '../types/dto'

const basePath = '/api/v1/learning'

export const learningRestService = {
  async listCandidates(): Promise<LearningCandidateDto[]> {
    return apiClient.get<LearningCandidateDto[]>(
      `${basePath}/candidates`,
    )
  },

  async getCandidate(
    candidateId: string,
  ): Promise<LearningCandidateDto> {
    return apiClient.get<LearningCandidateDto>(
      `${basePath}/candidates/${encodeURIComponent(candidateId)}`,
    )
  },

  async approveCandidate(
    candidateId: string,
  ): Promise<LearningCandidateDto> {
    return apiClient.post<LearningCandidateDto>(
      `${basePath}/candidates/${encodeURIComponent(candidateId)}/approve`,
      {},
    )
  },

  async rejectCandidate(
    candidateId: string,
  ): Promise<LearningCandidateDto> {
    return apiClient.post<LearningCandidateDto>(
      `${basePath}/candidates/${encodeURIComponent(candidateId)}/reject`,
      {},
    )
  },

  async listPatterns(): Promise<LearningPatternDto[]> {
    return apiClient.get<LearningPatternDto[]>(
      `${basePath}/patterns`,
    )
  },

  async listEvidence(): Promise<LearningEvidenceDto[]> {
    return apiClient.get<LearningEvidenceDto[]>(
      `${basePath}/evidence`,
    )
  },

  async listCallObservations(
    callId: string,
  ): Promise<CallObservationDto[]> {
    return apiClient.get<CallObservationDto[]>(
      `${basePath}/calls/${encodeURIComponent(callId)}/observations`,
    )
  },

  async submitFeedback(
    callId: string,
    request: LearningFeedbackRequestDto,
  ): Promise<LearningFeedbackDto> {
    return apiClient.post<LearningFeedbackDto>(
      `${basePath}/calls/${encodeURIComponent(callId)}/feedback`,
      request,
    )
  },

  async listImprovements(): Promise<ActiveImprovementDto[]> {
    return apiClient.get<ActiveImprovementDto[]>(
      `${basePath}/improvements`,
    )
  },

  async deactivateImprovement(
    improvementId: string,
  ): Promise<ActiveImprovementDto> {
    return apiClient.post<ActiveImprovementDto>(
      `${basePath}/improvements/${encodeURIComponent(improvementId)}/deactivate`,
      {},
    )
  },
}
