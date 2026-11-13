import io
import math
import wave
import numpy as np
from fastapi import HTTPException, status
from scipy import signal

TARGET_SAMPLE_RATE = 16000
MAX_DURATION_SECONDS = 30.0
MIN_SAMPLE_RATE = 8000
SILENCE_ENERGY_THRESHOLD = 0.002  # RMS threshold for silence detection


def decode_audio_bytes(data: bytes) -> tuple[np.ndarray, float]:
    """
    Decodes audio bytes (WAV, MP3, FLAC, or raw PCM) into 16 kHz mono float32 numpy array.
    Returns:
        (samples, duration_seconds)
    Raises:
        HTTPException(400) if audio cannot be decoded or sample rate < 8 kHz
        HTTPException(413) if duration > 30 seconds
    """
    if not data or len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty audio payload received",
        )

    samples: np.ndarray | None = None
    orig_sr: int | None = None

    # 1. Try PyAV first (handles MP3, WAV, FLAC, OGG, etc.)
    try:
        import av

        container = av.open(io.BytesIO(data))
        audio_stream = next((s for s in container.streams if s.type == "audio"), None)
        if audio_stream is not None:
            orig_sr = audio_stream.codec_context.sample_rate or audio_stream.rate
            if orig_sr and orig_sr < MIN_SAMPLE_RATE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Audio sample rate {orig_sr} Hz is below minimum required {MIN_SAMPLE_RATE} Hz",
                )

            # Resample directly to 16000 mono float32 using PyAV resampler
            resampler = av.AudioResampler(
                format="flt",
                layout="mono",
                rate=TARGET_SAMPLE_RATE,
            )
            chunks = []
            for frame in container.decode(audio=0):
                resampled_frames = resampler.resample(frame)
                for rf in resampled_frames:
                    chunks.append(rf.to_ndarray())

            if chunks:
                samples = np.concatenate(chunks, axis=1).squeeze(0)
    except HTTPException:
        raise
    except Exception:
        # Fall back to other decoders if PyAV fails on this input
        pass

    # 2. Try standard library wave module (standard WAV format)
    if samples is None:
        try:
            with wave.open(io.BytesIO(data), "rb") as wf:
                orig_sr = wf.getframerate()
                if orig_sr < MIN_SAMPLE_RATE:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Audio sample rate {orig_sr} Hz is below minimum required {MIN_SAMPLE_RATE} Hz",
                    )
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                raw_frames = wf.readframes(wf.getnframes())

                if sampwidth == 2:
                    raw_samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
                elif sampwidth == 1:
                    raw_samples = (np.frombuffer(raw_frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
                elif sampwidth == 4:
                    raw_samples = np.frombuffer(raw_frames, dtype=np.int32).astype(np.float32) / 2147483648.0
                else:
                    raise ValueError(f"Unsupported bit depth: {sampwidth * 8}")

                if n_channels > 1:
                    raw_samples = raw_samples.reshape(-1, n_channels).mean(axis=1)

                samples = resample_audio(raw_samples, orig_sr, TARGET_SAMPLE_RATE)
        except HTTPException:
            raise
        except Exception:
            pass

    # 3. Try raw 16-bit little-endian PCM at 16000 or 8000 Hz fallback
    if samples is None and len(data) % 2 == 0:
        try:
            raw_int16 = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
            # Assume 16kHz mono by default for raw PCM
            samples = raw_int16
        except Exception:
            pass

    if samples is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot decode audio file. Unsupported format or corrupted data.",
        )

    # Ensure float32 1-D array
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    duration = float(len(samples)) / TARGET_SAMPLE_RATE

    # Check 30 seconds limit
    if duration > MAX_DURATION_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Audio duration ({duration:.2f} s) exceeds maximum allowed duration of {MAX_DURATION_SECONDS} seconds",
        )

    return samples, duration


def resample_audio(samples: np.ndarray, orig_sr: int, target_sr: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    """Resamples mono audio to target_sr."""
    if orig_sr == target_sr:
        return samples

    gcd = math.gcd(orig_sr, target_sr)
    up = target_sr // gcd
    down = orig_sr // gcd
    resampled = signal.resample_poly(samples, up, down)
    return resampled.astype(np.float32)


def is_silence(samples: np.ndarray, threshold: float = SILENCE_ENERGY_THRESHOLD) -> bool:
    """Detects whether audio is silent / no speech using RMS energy."""
    if len(samples) == 0:
        return True
    rms = np.sqrt(np.mean(samples ** 2))
    return bool(rms < threshold)

