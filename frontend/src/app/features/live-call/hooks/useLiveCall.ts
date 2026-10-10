import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'

import { toUserErrorMessage } from '../../../api/errors'
import { authService } from '../../../auth/AuthService'

import {
  toCallAnalysisViewModel,
  toCallMetadataViewModel,
  toTranscriptTurnViewModel,
} from '../adapters/toViewModel'

import { callRestService } from '../services/callRestService'

import {
  liveCallSocket,
  type LiveSocketStatus,
} from '../services/liveCallSocket'

import type {
  LiveAnalysisEventDto,
  LiveErrorEventDto,
} from '../types/dto'

import type {
  CallAnalysisViewModel,
  CallMetadataViewModel,
  TranscriptTurnViewModel,
} from '../types/view-models'

// The WebSocket pushes every analysis update, so while it is connected the
// page only polls occasionally as a safety net (e.g. for changes made on
// other pages). While it is down, polling takes over until it reconnects.
const FALLBACK_POLL_INTERVAL_MS = 2500
const HEALTHY_POLL_INTERVAL_MS = 30000

export function pollIntervalFor(
  connectionStatus: LiveSocketStatus,
  isCompleted: boolean,
): number {
  if (isCompleted || connectionStatus === 'connected') {
    return HEALTHY_POLL_INTERVAL_MS
  }

  return FALLBACK_POLL_INTERVAL_MS
}

interface UseLiveCallResult {
  call: CallMetadataViewModel | null
  transcript: TranscriptTurnViewModel[]
  analysis: CallAnalysisViewModel | null
  connectionStatus: LiveSocketStatus
  isLoading: boolean
  isCompleting: boolean
  error: string | null
  loadCall: (callId: string) => Promise<void>
  completeCall: () => Promise<void>
  clearCall: () => void
}

export function useLiveCall(
  callId: string | null,
): UseLiveCallResult {
  const [call, setCall] =
    useState<CallMetadataViewModel | null>(null)

  const [transcript, setTranscript] =
    useState<TranscriptTurnViewModel[]>([])

  const [analysis, setAnalysis] =
    useState<CallAnalysisViewModel | null>(null)

  const [connectionStatus, setConnectionStatus] =
    useState<LiveSocketStatus>('disconnected')

  const [isLoading, setIsLoading] =
    useState(false)

  const [isCompleting, setIsCompleting] =
    useState(false)

  const [error, setError] =
    useState<string | null>(null)

  const activeCallIdRef =
    useRef<string | null>(null)

  // Whether the socket has connected since the call was loaded; a later
  // reconnect refreshes once to catch up on anything missed while down.
  const hasConnectedRef = useRef(false)

  const refreshCallState = useCallback(
    async (
      targetCallId: string,
      includeAnalysis = true,
    ) => {
      const callResponse =
        await callRestService.getCall(
          targetCallId,
        )

      if (
        activeCallIdRef.current !==
        targetCallId
      ) {
        return
      }

      setCall(
        toCallMetadataViewModel(
          callResponse,
        ),
      )

      setTranscript(
        callResponse.utterances.map(
          toTranscriptTurnViewModel,
        ),
      )

      if (!includeAnalysis) {
        return
      }

      try {
        const analysisResponse =
          await callRestService.getAnalysis(
            targetCallId,
          )

        if (
          activeCallIdRef.current !==
          targetCallId
        ) {
          return
        }

        setAnalysis(
          toCallAnalysisViewModel(
            analysisResponse,
          ),
        )
      } catch {
        // Transcript remains usable if analysis refresh fails.
      }
    },
    [],
  )

  const applyAnalysis = useCallback(
    async (event: LiveAnalysisEventDto) => {
      setAnalysis(
        toCallAnalysisViewModel(event),
      )

      try {
        // The event already carries the analysis; only the transcript and
        // call status need fetching.
        await refreshCallState(event.call_id, false)
      } catch {
        // Analysis remains usable even if transcript refresh fails.
      }
    },
    [refreshCallState],
  )

  const handleSocketError = useCallback(
    (event: LiveErrorEventDto) => {
      setError(event.message)
    },
    [],
  )

  const loadCall = useCallback(
    async (requestedCallId: string) => {
      const normalizedCallId =
        requestedCallId.trim()

      if (!normalizedCallId) {
        setError(
          'Enter a call ID to open a live call.',
        )
        return
      }

      if (!authService.getAccessToken()) {
        setError(
          'Your session is not available. Please sign in again.',
        )
        return
      }

      liveCallSocket.disconnect()

      activeCallIdRef.current =
        normalizedCallId
      hasConnectedRef.current = false

      setIsLoading(true)
      setError(null)
      setCall(null)
      setTranscript([])
      setAnalysis(null)
      setConnectionStatus('connecting')

      try {
        await refreshCallState(
          normalizedCallId,
        )

        if (
          activeCallIdRef.current !==
          normalizedCallId
        ) {
          return
        }

        liveCallSocket.connect(
          normalizedCallId,
          {
            onStatusChange:
              setConnectionStatus,

            onAnalysis: (event) => {
              void applyAnalysis(event)
            },

            onError:
              handleSocketError,
          },
        )
      } catch (loadError) {
        if (
          activeCallIdRef.current ===
          normalizedCallId
        ) {
          setError(
            toUserErrorMessage(
              loadError,
              'Unable to load the live call.',
            ),
          )

          setConnectionStatus('error')
        }
      } finally {
        if (
          activeCallIdRef.current ===
          normalizedCallId
        ) {
          setIsLoading(false)
        }
      }
    },
    [
      applyAnalysis,
      handleSocketError,
      refreshCallState,
    ],
  )

  const completeCall = useCallback(
    async () => {
      const targetCallId =
        activeCallIdRef.current

      if (!targetCallId) {
        return
      }

      setIsCompleting(true)
      setError(null)

      try {
        const callResponse =
          await callRestService.completeCall(
            targetCallId,
          )

        if (
          activeCallIdRef.current !==
          targetCallId
        ) {
          return
        }

        setCall(
          toCallMetadataViewModel(
            callResponse,
          ),
        )

        await refreshCallState(
          targetCallId,
        )
        liveCallSocket.disconnect()
      } catch (completeError) {
        if (
          activeCallIdRef.current ===
          targetCallId
        ) {
          setError(
            toUserErrorMessage(
              completeError,
              'Unable to complete the call.',
            ),
          )
        }
      } finally {
        if (
          activeCallIdRef.current ===
          targetCallId
        ) {
          setIsCompleting(false)
        }
      }
    },
    [refreshCallState],
  )

  const clearCall = useCallback(() => {
    activeCallIdRef.current = null

    liveCallSocket.disconnect()

    setCall(null)
    setTranscript([])
    setAnalysis(null)

    setConnectionStatus(
      'disconnected',
    )

    setError(null)
    setIsLoading(false)
    setIsCompleting(false)
  }, [])

  useEffect(() => {
    if (!callId) {
      return
    }

    let cancelled = false

    const startLoading = async () => {
      if (cancelled) {
        return
      }

      await loadCall(callId)
    }

    void startLoading()

    return () => {
      cancelled = true

      activeCallIdRef.current = null

      liveCallSocket.disconnect()
    }
  }, [callId, loadCall])

  const loadedCallId = call?.callId ?? null
  const isCompleted =
    call?.status.toLowerCase() === 'completed'

  useEffect(() => {
    if (!callId || !loadedCallId) {
      return
    }

    const refresh = () => {
      if (
        activeCallIdRef.current !==
        callId
      ) {
        return
      }

      void refreshCallState(callId).catch(
        () => {
          // Keep showing the last successful snapshot.
        },
      )
    }

    if (connectionStatus === 'connected') {
      if (hasConnectedRef.current) {
        refresh()
      }

      hasConnectedRef.current = true
    }

    const intervalId = window.setInterval(
      refresh,
      pollIntervalFor(
        connectionStatus,
        isCompleted,
      ),
    )

    return () => {
      window.clearInterval(intervalId)
    }
  }, [
    loadedCallId,
    callId,
    connectionStatus,
    isCompleted,
    refreshCallState,
  ])

  return {
    call,
    transcript,
    analysis,
    connectionStatus,
    isLoading,
    isCompleting,
    error,
    loadCall,
    completeCall,
    clearCall,
  }
}
