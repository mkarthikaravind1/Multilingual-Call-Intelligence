import { authService } from '../../../auth/AuthService'

import type {
  LiveAnalysisEventDto,
  LiveErrorEventDto,
  LiveUtteranceMessageDto,
} from '../types/dto'

const DEFAULT_API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 10000
const MAX_RECONNECT_ATTEMPTS = 5

export type LiveSocketStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'error'
  | 'closed'

export interface LiveCallSocketHandlers {
  onStatusChange: (status: LiveSocketStatus) => void
  onAnalysis: (event: LiveAnalysisEventDto) => void
  onError: (event: LiveErrorEventDto) => void
}

export function toWebSocketBaseUrl(apiBaseUrl: string): string {
  // An empty base URL means "same origin" (the API behind the web server).
  const url = new URL(apiBaseUrl || window.location.origin, window.location.origin)

  url.protocol =
    url.protocol === 'https:'
      ? 'wss:'
      : 'ws:'

  url.pathname = url.pathname.replace(/\/$/, '')
  url.search = ''
  url.hash = ''

  return url.toString().replace(/\/$/, '')
}

function isLiveAnalysisEvent(
  value: unknown,
): value is LiveAnalysisEventDto {
  if (!value || typeof value !== 'object') {
    return false
  }

  const record = value as Record<string, unknown>

  return (
    record.type === 'analysis' &&
    typeof record.call_id === 'string'
  )
}

function isLiveErrorEvent(
  value: unknown,
): value is LiveErrorEventDto {
  if (!value || typeof value !== 'object') {
    return false
  }

  const record = value as Record<string, unknown>

  return (
    record.type === 'error' &&
    typeof record.message === 'string'
  )
}

export class LiveCallSocket {
  private socket: WebSocket | null = null
  private callId: string | null = null
  private handlers: LiveCallSocketHandlers | null = null
  private reconnectTimer: number | null = null
  private reconnectAttempts = 0
  private manuallyClosed = false
  private terminal = false

  connect(
    callId: string,
    handlers: LiveCallSocketHandlers,
  ) {
    this.disconnect()

    this.callId = callId
    this.handlers = handlers
    this.manuallyClosed = false
    this.terminal = false
    this.reconnectAttempts = 0

    this.openSocket(false)
  }

  sendUtterance(
    message: LiveUtteranceMessageDto,
  ): boolean {
    if (
      !this.socket ||
      this.socket.readyState !== WebSocket.OPEN
    ) {
      return false
    }

    this.socket.send(JSON.stringify(message))

    return true
  }

  disconnect() {
    this.manuallyClosed = true
    this.terminal = true

    this.clearReconnectTimer()

    const socket = this.socket
    this.socket = null

    if (socket) {
      socket.close(1000, 'Live call closed')
    }

    this.handlers?.onStatusChange('closed')

    this.callId = null
    this.handlers = null
  }

  private openSocket(isReconnect: boolean) {
    const callId = this.callId
    const token = authService.getAccessToken()

    if (
      !callId ||
      !token ||
      this.manuallyClosed ||
      this.terminal
    ) {
      this.handlers?.onStatusChange('error')
      return
    }

    this.handlers?.onStatusChange(
      isReconnect
        ? 'reconnecting'
        : 'connecting',
    )

    const baseUrl =
      toWebSocketBaseUrl(DEFAULT_API_BASE_URL)

    const url =
      `${baseUrl}/api/v1/calls/` +
      `${encodeURIComponent(callId)}/live` +
      `?token=${encodeURIComponent(token)}`

    const socket = new WebSocket(url)

    this.socket = socket

    socket.onopen = () => {
      this.reconnectAttempts = 0
      this.handlers?.onStatusChange('connected')
    }

    socket.onmessage = (event) => {
      this.handleMessage(event.data)
    }

    socket.onerror = () => {
      this.handlers?.onStatusChange('error')
    }

    socket.onclose = (event) => {
      if (this.socket === socket) {
        this.socket = null
      }

      if (
        this.manuallyClosed ||
        this.terminal
      ) {
        return
      }

      if (event.code === 4404) {
        this.terminal = true
        this.handlers?.onStatusChange('error')
        return
      }

      if (event.code === 4401) {
        this.terminal = true
        this.handlers?.onError({
          type: 'error',
          code: 'internal_error',
          call_id: callId ?? '',
          message: 'Could not validate credentials.',
        })
        this.handlers?.onStatusChange('error')
        return
      }

      this.scheduleReconnect()
    }
  }

  private handleMessage(rawData: unknown) {
    if (typeof rawData !== 'string') {
      this.handlers?.onStatusChange('error')
      return
    }

    let payload: unknown

    try {
      payload = JSON.parse(rawData)
    } catch {
      this.handlers?.onStatusChange('error')
      return
    }

    if (isLiveAnalysisEvent(payload)) {
      this.handlers?.onAnalysis(payload)
      return
    }

    if (isLiveErrorEvent(payload)) {
      this.handlers?.onError(payload)

      if (payload.code === 'call_not_found') {
        this.terminal = true
      }

      return
    }

    this.handlers?.onStatusChange('error')
  }

  private scheduleReconnect() {
    if (
      this.reconnectAttempts >=
      MAX_RECONNECT_ATTEMPTS
    ) {
      this.handlers?.onStatusChange('error')
      return
    }

    const delay = Math.min(
      RECONNECT_BASE_DELAY_MS *
        2 ** this.reconnectAttempts,
      RECONNECT_MAX_DELAY_MS,
    )

    this.reconnectAttempts += 1

    this.clearReconnectTimer()

    this.handlers?.onStatusChange(
      'reconnecting',
    )

    this.reconnectTimer =
      window.setTimeout(() => {
        this.reconnectTimer = null
        this.openSocket(true)
      }, delay)
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(
        this.reconnectTimer,
      )

      this.reconnectTimer = null
    }
  }
}

export const liveCallSocket =
  new LiveCallSocket()