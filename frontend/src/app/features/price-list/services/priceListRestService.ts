import { apiClient } from '../../../api/client'

import type {
  PriceListDto,
  PriceListPreviewDto,
  PriceListVersionDto,
  SavePriceListDto,
} from '../types/dto'

const basePath = '/api/v1/price-list'

export const priceListRestService = {
  get(): Promise<PriceListDto> {
    return apiClient.get<PriceListDto>(basePath)
  },

  save(payload: SavePriceListDto): Promise<PriceListDto> {
    return apiClient.put<PriceListDto>(basePath, payload)
  },

  // Reads and checks an uploaded sheet; nothing is saved.
  preview(file: File): Promise<PriceListPreviewDto> {
    const form = new FormData()
    form.append('file', file)
    return apiClient.request<PriceListPreviewDto>(`${basePath}/preview`, {
      method: 'POST',
      body: form,
    })
  },

  export(format: 'xlsx' | 'csv'): Promise<Blob> {
    return apiClient.download(`${basePath}/export?format=${format}`)
  },

  listVersions(): Promise<PriceListVersionDto[]> {
    return apiClient.get<PriceListVersionDto[]>(`${basePath}/versions`)
  },

  restore(versionId: number): Promise<PriceListDto> {
    return apiClient.post<PriceListDto>(`${basePath}/versions/${versionId}/restore`, {})
  },
}
