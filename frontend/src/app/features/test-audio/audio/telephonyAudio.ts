// Turns any recording the browser can decode (MP3, WAV, M4A, OGG…) into the
// audio Plivo streams live calls in (PLIVO_STREAM_AUDIO=l16_16k): 16 kHz
// mono, 16-bit little-endian linear PCM, 20 ms frames.

export const TELEPHONY_SAMPLE_RATE = 16000
export const TELEPHONY_ENCODING = 'audio/x-l16'
export const FRAME_SAMPLES = 320 // 20 ms at 16 kHz

export async function decodeRecording(
  file: File,
  context: BaseAudioContext,
): Promise<AudioBuffer> {
  const bytes = await file.arrayBuffer()
  try {
    return await context.decodeAudioData(bytes)
  } catch {
    throw new Error(`The browser could not decode "${file.name}". Try an MP3 or WAV file.`)
  }
}

export async function toTelephonyPcm(recording: AudioBuffer): Promise<Float32Array> {
  const length = Math.ceil(recording.duration * TELEPHONY_SAMPLE_RATE)
  // A one-channel offline context downmixes stereo and resamples on render.
  const offline = new OfflineAudioContext(1, length, TELEPHONY_SAMPLE_RATE)
  const source = offline.createBufferSource()
  source.buffer = recording
  source.connect(offline.destination)
  source.start()
  const rendered = await offline.startRendering()
  return rendered.getChannelData(0)
}

export function encodeFrameBase64(pcm: Float32Array, frameIndex: number): string {
  const start = frameIndex * FRAME_SAMPLES
  const end = Math.min(start + FRAME_SAMPLES, pcm.length)
  let binary = ''
  for (let i = start; i < end; i += 1) {
    const sample = Math.round(Math.max(-1, Math.min(1, pcm[i])) * 32767) & 0xffff
    binary += String.fromCharCode(sample & 0xff, sample >> 8)
  }
  return btoa(binary)
}

export function frameCount(pcm: Float32Array): number {
  return Math.ceil(pcm.length / FRAME_SAMPLES)
}
