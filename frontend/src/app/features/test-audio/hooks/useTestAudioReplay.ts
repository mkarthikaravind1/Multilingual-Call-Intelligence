import { useCallback, useEffect, useRef, useState } from 'react'

import { toUserErrorMessage } from '../../../api/errors'
import { toWebSocketBaseUrl } from '../../live-call/services/liveCallSocket'
import {
  FRAME_SAMPLES,
  TELEPHONY_SAMPLE_RATE,
  decodeRecording,
  encodeFrameBase64,
  frameCount,
  toTelephonyPcm,
} from '../audio/telephonyAudio'
import { testCallRestService } from '../services/testCallRestService'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const PUMP_INTERVAL_MS = 100

export type ReplayPhase = 'idle' | 'preparing' | 'streaming' | 'ending' | 'finished' | 'error'

interface ReplaySession {
  providerCallId: string
  context: AudioContext
  source: AudioBufferSourceNode
  socket: WebSocket
  pcm: Float32Array
  totalFrames: number
  sentFrames: number
  startedAt: number
  timer: number | null
  ended: boolean
}

export interface TestAudioReplay {
  phase: ReplayPhase
  fileName: string | null
  callId: string | null
  elapsedSeconds: number
  durationSeconds: number
  error: string | null
  start: (file: File, fromNumber: string) => Promise<void>
  stop: () => void
  reset: () => Promise<void>
}

// Plays a recording aloud while streaming it, in real time, to the call's
// telephony stream exactly as the phone provider would: a "start" event,
// 20 ms mu-law "media" frames, then "stop" — and finally the hang-up.
export function useTestAudioReplay(onCallStarted: (callId: string) => void): TestAudioReplay {
  const [phase, setPhase] = useState<ReplayPhase>('idle')
  const [fileName, setFileName] = useState<string | null>(null)
  const [callId, setCallId] = useState<string | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [durationSeconds, setDurationSeconds] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const sessionRef = useRef<ReplaySession | null>(null)

  const finish = useCallback(async (session: ReplaySession, failure: string | null) => {
    if (session.ended) return
    session.ended = true
    if (session.timer !== null) window.clearInterval(session.timer)
    try {
      session.source.stop()
    } catch {
      // already stopped
    }
    void session.context.close()

    if (session.socket.readyState === WebSocket.OPEN) {
      session.socket.send(JSON.stringify({ event: 'stop' }))
    }
    setPhase('ending')

    const streamedSeconds = (session.sentFrames * FRAME_SAMPLES) / TELEPHONY_SAMPLE_RATE
    try {
      await testCallRestService.end(session.providerCallId, streamedSeconds)
    } catch (err) {
      failure ??= toUserErrorMessage(err, 'The recording finished but the call could not be ended.')
    }
    session.socket.close()
    if (sessionRef.current === session) sessionRef.current = null

    setError(failure)
    setPhase(failure ? 'error' : 'finished')
  }, [])

  const pump = useCallback(
    (session: ReplaySession) => {
      const elapsed = session.context.currentTime - session.startedAt
      const due = Math.min(
        session.totalFrames,
        Math.floor((elapsed * TELEPHONY_SAMPLE_RATE) / FRAME_SAMPLES),
      )
      while (session.sentFrames < due) {
        const index = session.sentFrames
        session.socket.send(
          JSON.stringify({
            event: 'media',
            media: {
              track: 'inbound',
              chunk: index + 1,
              timestamp: String(Math.round((index * FRAME_SAMPLES * 1000) / TELEPHONY_SAMPLE_RATE)),
              payload: encodeFrameBase64(session.pcm, index),
            },
          }),
        )
        session.sentFrames += 1
      }
      setElapsedSeconds(Math.min(elapsed, session.pcm.length / TELEPHONY_SAMPLE_RATE))
      if (session.sentFrames >= session.totalFrames) {
        void finish(session, null)
      }
    },
    [finish],
  )

  const start = useCallback(
    async (file: File, fromNumber: string) => {
      if (sessionRef.current) return
      setPhase('preparing')
      setError(null)
      setFileName(file.name)
      setCallId(null)
      setElapsedSeconds(0)

      let context: AudioContext | null = null
      try {
        context = new AudioContext()
        const recording = await decodeRecording(file, context)
        const pcm = await toTelephonyPcm(recording)
        setDurationSeconds(pcm.length / TELEPHONY_SAMPLE_RATE)

        const started = await testCallRestService.start(fromNumber.trim())
        setCallId(started.call_id)
        onCallStarted(started.call_id)

        const socket = new WebSocket(`${toWebSocketBaseUrl(API_BASE_URL)}${started.stream_path}`)
        const source = context.createBufferSource()
        source.buffer = recording
        source.connect(context.destination)

        const session: ReplaySession = {
          providerCallId: started.provider_call_id,
          context,
          source,
          socket,
          pcm,
          totalFrames: frameCount(pcm),
          sentFrames: 0,
          startedAt: 0,
          timer: null,
          ended: false,
        }
        sessionRef.current = session

        socket.onopen = () => {
          socket.send(
            JSON.stringify({
              event: 'start',
              start: {
                callId: started.provider_call_id,
                streamId: started.provider_call_id,
                tracks: ['inbound'],
                mediaFormat: { encoding: 'audio/x-mulaw', sampleRate: TELEPHONY_SAMPLE_RATE },
              },
            }),
          )
          void session.context.resume()
          session.startedAt = session.context.currentTime
          source.start()
          setPhase('streaming')
          session.timer = window.setInterval(() => pump(session), PUMP_INTERVAL_MS)
        }
        socket.onclose = (event) => {
          if (!session.ended) {
            void finish(
              session,
              `The server closed the audio stream (code ${event.code}). The call was ended early.`,
            )
          }
        }
      } catch (err) {
        void context?.close()
        setError(toUserErrorMessage(err, 'Could not start the test call.'))
        setPhase('error')
      }
    },
    [finish, onCallStarted, pump],
  )

  const stop = useCallback(() => {
    const session = sessionRef.current
    if (session) void finish(session, null)
  }, [finish])

  // Hangs up a replay still in progress, then forgets the recording.
  const reset = useCallback(async () => {
    const session = sessionRef.current
    if (session) await finish(session, null)
    setPhase('idle')
    setFileName(null)
    setCallId(null)
    setElapsedSeconds(0)
    setDurationSeconds(0)
    setError(null)
  }, [finish])

  // Leaving the page hangs up rather than leaving the call active.
  useEffect(
    () => () => {
      const session = sessionRef.current
      if (session) void finish(session, null)
    },
    [finish],
  )

  return { phase, fileName, callId, elapsedSeconds, durationSeconds, error, start, stop, reset }
}
