import { ApiError, getErrorMessage } from './errors'

const DEFAULT_API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface ApiErrorHandlers {
  onUnauthorized?: () => void
  onForbidden?: () => void
}

export class ApiClient {
  private readonly baseUrl: string
  private accessToken: string | null
  private errorHandlers: ApiErrorHandlers = {}

  constructor(baseUrl = DEFAULT_API_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/$/, '')
    this.accessToken = null
  }

  setAccessToken(token: string | null) {
    this.accessToken = token
  }

  setErrorHandlers(handlers: ApiErrorHandlers) {
    this.errorHandlers = handlers
  }

  getAccessToken() {
    return this.accessToken
  }

  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`
    const url = `${this.baseUrl}${normalizedPath}`
    const headers = new Headers(options.headers ?? {})

    if (!(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json')
    }

    if (this.accessToken) {
      headers.set('Authorization', `Bearer ${this.accessToken}`)
    }

    let response: Response
    try {
      response = await fetch(url, {
        ...options,
        headers,
      })
    } catch (error) {
      throw new ApiError(500, 'Unable to reach the server. Please try again.', error)
    }

    const rawBody = await response.text()
    let payload: unknown = null

    if (rawBody) {
      try {
        payload = JSON.parse(rawBody)
      } catch {
        payload = rawBody
      }
    }

    if (!response.ok) {
      const message = getErrorMessage(payload, 'Request failed.')

      if (response.status === 401) {
        this.errorHandlers.onUnauthorized?.()
      }

      if (response.status === 403) {
        this.errorHandlers.onForbidden?.()
      }

      throw new ApiError(response.status, message, payload)
    }

    if (rawBody.length === 0) {
      return undefined as T
    }

    return payload as T
  }

  get<T>(path: string, init?: RequestInit) {
    return this.request<T>(path, { ...init, method: 'GET' })
  }

  post<T>(path: string, body: unknown, init?: RequestInit) {
    return this.request<T>(path, {
      ...init,
      method: 'POST',
      body: JSON.stringify(body),
    })
  }
}

export const apiClient = new ApiClient()
