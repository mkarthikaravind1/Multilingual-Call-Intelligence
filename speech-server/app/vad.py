import math
from typing import Callable, Optional, Tuple
import numpy as np


class StreamVADProcessor:
    """
    Real-time Voice Activity Detector and audio chunker for streaming WebSocket audio.
    Tracks timestamps relative to the first byte of the connection.
    Supports Silero VAD (PyTorch / ONNX) with high-efficiency energy-based fallback.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        pause_ms: int = 250,
        max_segment_seconds: float = 8.0,
        energy_threshold: float = 0.012,
    ):
        self.sample_rate = sample_rate
        self.pause_ms = pause_ms
        self.pause_seconds = pause_ms / 1000.0
        self.max_segment_seconds = float(max_segment_seconds)
        self.energy_threshold = energy_threshold

        # Total audio samples processed since connection opened
        self.total_samples_received: int = 0

        # VAD state
        self.in_speech: bool = False
        self.current_speech_start_time: Optional[float] = None
        self.silence_samples_accumulated: int = 0
        self.speech_buffer: list[np.ndarray] = []

        # Silero VAD model if available
        self._silero_model = None
        self._init_silero()

    def _init_silero(self) -> None:
        try:
            import torch
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                trust_repo=True,
                verbose=False,
            )
            self._silero_model = model
        except Exception:
            self._silero_model = None

    def _is_frame_speech(self, frame: np.ndarray) -> bool:
        """Determines if a short frame (e.g. 512 samples / 32ms) contains speech."""
        if len(frame) == 0:
            return False

        # If Silero VAD is loaded and frame is 512 samples (for 16kHz)
        if self._silero_model is not None and len(frame) == 512 and self.sample_rate == 16000:
            try:
                import torch
                tensor = torch.from_numpy(frame).float()
                prob = self._silero_model(tensor, self.sample_rate).item()
                return prob >= 0.5
            except Exception:
                pass

        # Energy-based VAD calculation
        rms = float(np.sqrt(np.mean(frame ** 2)))
        return rms > self.energy_threshold

    def process_pcm_chunk(
        self,
        pcm_bytes: bytes,
    ) -> list[Tuple[str, dict]]:
        """
        Ingests a 16-bit little-endian PCM chunk.
        Returns a list of events:
            ("speech_start", {"at": timestamp})
            ("speech_end", {"at": timestamp})
            ("segment_ready", {"audio": np.ndarray, "start": start_time, "end": end_time})
        """
        if not pcm_bytes:
            return []

        # Convert int16 PCM to float32 normalized [-1.0, 1.0]
        int16_samples = np.frombuffer(pcm_bytes, dtype="<i2")
        samples = int16_samples.astype(np.float32) / 32768.0

        events = []
        frame_size = 512  # 32ms at 16kHz
        pause_samples = int(self.pause_seconds * self.sample_rate)
        max_segment_samples = int(self.max_segment_seconds * self.sample_rate)

        # Process frame by frame
        for i in range(0, len(samples), frame_size):
            frame = samples[i : i + frame_size]
            frame_len = len(frame)
            frame_start_time = float(self.total_samples_received) / self.sample_rate
            self.total_samples_received += frame_len

            is_speech = self._is_frame_speech(frame)

            if is_speech:
                if not self.in_speech:
                    self.in_speech = True
                    self.current_speech_start_time = round(frame_start_time, 2)
                    self.silence_samples_accumulated = 0
                    self.speech_buffer = [frame]
                    events.append(("speech_start", {"at": self.current_speech_start_time}))
                else:
                    self.silence_samples_accumulated = 0
                    self.speech_buffer.append(frame)

                # Check if current utterance exceeds max_segment_seconds
                current_speech_len = sum(len(f) for f in self.speech_buffer)
                if current_speech_len >= max_segment_samples:
                    speech_end_time = round(float(self.total_samples_received) / self.sample_rate, 2)
                    events.append(("speech_end", {"at": speech_end_time}))

                    combined_audio = np.concatenate(self.speech_buffer)
                    events.append(
                        (
                            "segment_ready",
                            {
                                "audio": combined_audio,
                                "start": self.current_speech_start_time,
                                "end": speech_end_time,
                            },
                        )
                    )

                    # Reset for next part of continuing speech
                    self.current_speech_start_time = speech_end_time
                    self.speech_buffer = []
                    events.append(("speech_start", {"at": self.current_speech_start_time}))
            else:
                # Silence frame
                if self.in_speech:
                    self.silence_samples_accumulated += frame_len
                    self.speech_buffer.append(frame)

                    # Silence exceeded pause_ms threshold
                    if self.silence_samples_accumulated >= pause_samples:
                        # Exclude trailing silence from speech duration
                        effective_speech_samples = sum(len(f) for f in self.speech_buffer) - self.silence_samples_accumulated
                        effective_speech_samples = max(0, effective_speech_samples)

                        start_t = self.current_speech_start_time or 0.0
                        speech_end_time = round(start_t + (effective_speech_samples / self.sample_rate), 2)
                        events.append(("speech_end", {"at": speech_end_time}))

                        if self.speech_buffer:
                            combined_audio = np.concatenate(self.speech_buffer)
                            events.append(
                                (
                                    "segment_ready",
                                    {
                                        "audio": combined_audio,
                                        "start": start_t,
                                        "end": speech_end_time,
                                    },
                                )
                            )

                        # Reset state
                        self.in_speech = False
                        self.current_speech_start_time = None
                        self.silence_samples_accumulated = 0
                        self.speech_buffer = []

        return events

    def finalize(self) -> list[Tuple[str, dict]]:
        """Called when {"type": "end"} is received; flushes any remaining speech buffer."""
        events = []
        if self.in_speech and self.speech_buffer:
            effective_speech_samples = sum(len(f) for f in self.speech_buffer) - self.silence_samples_accumulated
            effective_speech_samples = max(0, effective_speech_samples)

            start_t = self.current_speech_start_time or 0.0
            speech_end_time = round(start_t + (effective_speech_samples / self.sample_rate), 2)
            events.append(("speech_end", {"at": speech_end_time}))

            combined_audio = np.concatenate(self.speech_buffer)
            events.append(
                (
                    "segment_ready",
                    {
                        "audio": combined_audio,
                        "start": start_t,
                        "end": speech_end_time,
                    },
                )
            )

            self.in_speech = False
            self.current_speech_start_time = None
            self.silence_samples_accumulated = 0
            self.speech_buffer = []

        return events

