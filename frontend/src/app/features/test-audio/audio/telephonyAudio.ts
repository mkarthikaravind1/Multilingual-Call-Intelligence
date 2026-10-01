// Turns any recording the browser can decode (MP3, WAV, M4A, OGG…) into the
// audio a phone line carries: 8 kHz mono, 8-bit mu-law, 20 ms frames.

export const TELEPHONY_SAMPLE_RATE = 8000
export const FRAME_SAMPLES = 160 // 20 ms at 8 kHz

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

const SEGMENT_ENDS = [0x3f, 0x7f, 0xff, 0x1ff, 0x3ff, 0x7ff, 0xfff, 0x1fff]

// G.711 mu-law, a port of CPython's audioop.lin2ulaw (the backend decodes
// with audioop.ulaw2lin).
function encodeMuLawSample(sample: number): number {
  let value = Math.round(Math.max(-1, Math.min(1, sample)) * 32767) >> 2
  let mask = 0xff
  if (value < 0) {
    value = -value
    mask = 0x7f
  }
  value = Math.min(value, 8159) + 33
  const segment = SEGMENT_ENDS.findIndex((end) => value <= end)
  if (segment < 0) return 0x7f ^ mask
  return ((segment << 4) | ((value >> (segment + 1)) & 0x0f)) ^ mask
}

export function encodeFrameBase64(pcm: Float32Array, frameIndex: number): string {
  const start = frameIndex * FRAME_SAMPLES
  const end = Math.min(start + FRAME_SAMPLES, pcm.length)
  let binary = ''
  for (let i = start; i < end; i += 1) {
    binary += String.fromCharCode(encodeMuLawSample(pcm[i]))
  }
  return btoa(binary)
}

export function frameCount(pcm: Float32Array): number {
  return Math.ceil(pcm.length / FRAME_SAMPLES)
}
