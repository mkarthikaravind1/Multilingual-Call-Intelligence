import { ApiError } from '../../../api/errors'
import { callRestService } from './callRestService'

import type {
  LiveAnalysisEventDto,
  LiveErrorEventDto,
  LiveUtteranceMessageDto,
} from '../types/dto'

const DEFAULT_API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// Reconnects back off exponentially (with jitter) up to this cap and keep
// trying for as long as the call is open; the page polls meanwhile.
const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 30000

const AUTH_FAILED_CLOSE_CODE = 4401
const CALL_NOT_FOUND_CLOSE_CODE = 4404
// A ticket is single-use and short-lived, so one rejected ticket is retried
// with a fresh one; repeated rejections mean the user may no longer connect.
const MAX_CONSECUTIVE_AUTH_FAILURES = 2

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
  private authFailures = 0
  private terminal = false
  // Increases on every connect/disconnect, so a ticket request that
  // resolves after the call was closed or switched is ignored.
  private generation = 0

  connect(
    callId: string,
    handlers: LiveCallSocketHandlers,
  ) {
    this.disconnect()

    this.callId = callId
    this.handlers = handlers
    this.terminal = false
    this.reconnectAttempts = 0
    this.authFailures = 0

    void this.openSocket(false)
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
    this.generation += 1
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

  private async openSocket(isReconnect: boolean) {
    const callId = this.callId
    const generation = this.generation

    if (!callId || this.terminal) {
      return
    }

    this.handlers?.onStatusChange(
      isReconnect
        ? 'reconnecting'
        : 'connecting',
    )

    let ticket: string

    try {
      ticket = (await callRestService.createLiveToken(callId)).token
    } catch (error) {
      if (generation !== this.generation) {
        return
      }

      if (
        error instanceof ApiError &&
        [401, 403, 404].includes(error.status)
      ) {
        // Signed out, not allowed, or no such call: retrying cannot help.
        this.fail(callId, error.message)
        return
      }

      this.scheduleReconnect()
      return
    }

    if (generation !== this.generation) {
      return
    }

    const baseUrl =
      toWebSocketBaseUrl(DEFAULT_API_BASE_URL)

    const url =
      `${baseUrl}/api/v1/calls/` +
      `${encodeURIComponent(callId)}/live` +
      `?ticket=${encodeURIComponent(ticket)}`

    const socket = new WebSocket(url)

    this.socket = socket

    socket.onopen = () => {
      this.reconnectAttempts = 0
      this.handlers?.onStatusChange('connected')
    }

    socket.onmessage = (event) => {
      this.authFailures = 0
      this.handleMessage(event.data)
    }

    socket.onerror = () => {
      // onclose follows and decides whether to reconnect.
    }

    socket.onclose = (event) => {
      if (this.socket === socket) {
        this.socket = null
      }

      if (
        this.terminal ||
        generation !== this.generation
      ) {
        return
      }

      if (event.code === CALL_NOT_FOUND_CLOSE_CODE) {
        this.terminal = true
        this.handlers?.onStatusChange('error')
        return
      }

      if (event.code !== AUTH_FAILED_CLOSE_CODE) {
        this.authFailures = 0
      } else {
        this.authFailures += 1

        if (
          this.authFailures >=
          MAX_CONSECUTIVE_AUTH_FAILURES
        ) {
          this.fail(callId, 'Could not validate credentials.')
          return
        }
      }

      this.scheduleReconnect()
    }
  }

  private fail(callId: string, message: string) {
    this.terminal = true
    this.handlers?.onError({
      type: 'error',
      code: 'internal_error',
      call_id: callId,
      message,
    })
    this.handlers?.onStatusChange('error')
  }

  private handleMessage(rawData: unknown) {
    if (typeof rawData !== 'string') {
      return
    }

    let payload: unknown

    try {
      payload = JSON.parse(rawData)
    } catch {
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
    }
  }

  private scheduleReconnect() {
    const delay = Math.min(
      RECONNECT_BASE_DELAY_MS *
        2 ** this.reconnectAttempts,
      RECONNECT_MAX_DELAY_MS,
    )

    // Jitter keeps many browsers from reconnecting in lockstep after an
    // API restart.
    const jitteredDelay =
      delay * (0.8 + Math.random() * 0.4)

    this.reconnectAttempts += 1

    this.clearReconnectTimer()

    this.handlers?.onStatusChange(
      'reconnecting',
    )

    this.reconnectTimer =
      window.setTimeout(() => {
        this.reconnectTimer = null
        void this.openSocket(true)
      }, jitteredDelay)
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