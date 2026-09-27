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

const POLL_INTERVAL_MS = 2500

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

  const refreshCallState = useCallback(
    async (targetCallId: string) => {
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
        await refreshCallState(event.call_id)
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
            {
              end_time: Date.now() / 1000,
            },
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

  useEffect(() => {
    if (!callId || !call) {
      return
    }

    const intervalId = window.setInterval(
      () => {
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
      },
      POLL_INTERVAL_MS,
    )

    return () => {
      window.clearInterval(intervalId)
    }
  }, [call?.callId, callId, refreshCallState])

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
