import { apiClient } from '../../../api/client'

import type {
  LearningCandidateDto,
  LearningEvidenceDto,
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
}