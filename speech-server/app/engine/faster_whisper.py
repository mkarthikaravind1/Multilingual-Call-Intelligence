import asyncio
import math
from typing import Optional
import numpy as np
from app.audio import is_silence
from app.engine.base import BaseSTTEngine, Segment, TranscriptionResponse

VALID_LANGUAGES = {"ta", "en", "te", "kn", "ml"}

# Language specific initial prompts to encourage preserving English terms in Latin script
INITIAL_PROMPTS = {
    "ta": "Automotive service center call: brake oil, engine inspection, car service, billing, tyre pressure.",
    "te": "Automotive service center call: engine oil, car checkup, spare parts, brake repair, appointment.",
    "kn": "Automotive service center call: vehicle service, maintenance, battery check, mileage, spare parts.",
    "ml": "Automotive service center call: vehicle maintenance, engine check, servicing date, complaint.",
    "en": "Automotive service center call: customer complaint, repair estimation, engine service.",
}


class FasterWhisperEngine(BaseSTTEngine):
    """Production STT Engine using faster-whisper / CTranslate2."""

    def __init__(
        self,
        model_name_or_path: str = "openai/whisper-large-v3-turbo",
        device: str = "auto",
        compute_type: str = "auto",
        max_concurrent: int = 10,
    ):
        self.model_name_or_path = model_name_or_path
        self._requested_device = device
        self._requested_compute_type = compute_type
        self.device = "cpu"
        self.compute_type = "float32"
        self.model = None
        self._loaded = False
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def load(self) -> None:
        from faster_whisper import WhisperModel
        import torch

        # Device determination
        if self._requested_device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = self._requested_device

        # Compute type determination
        if self._requested_compute_type == "auto":
            if self.device == "cuda":
                self.compute_type = "float16"
            else:
                self.compute_type = "int8"
        else:
            self.compute_type = self._requested_compute_type

        # Initialize faster-whisper model
        self.model = WhisperModel(
            self.model_name_or_path,
            device=self.device,
            compute_type=self.compute_type,
            download_root=None,
        )
        self._loaded = True

    def is_loaded(self) -> bool:
        return self._loaded

    def get_info(self) -> dict:
        return {
            "model": self.model_name_or_path,
            "device": self.device,
            "compute_type": self.compute_type,
        }

    async def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: Optional[str] = None,
        with_timestamps: bool = True,
    ) -> TranscriptionResponse:
        if not self._loaded or self.model is None:
            raise RuntimeError("Model is not loaded yet")

        duration = float(len(audio)) / sample_rate

        # 1. Quick silence check
        if is_silence(audio) or len(audio) == 0:
            return TranscriptionResponse(
                transcript="",
                language=language or "en",
                confidence=None,
                duration=round(duration, 3),
                no_speech=True,
                segments=[],
            )

        # 2. Run inference in worker thread pool under concurrency limit
        async with self._semaphore:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                self._sync_transcribe,
                audio,
                duration,
                language,
                with_timestamps,
            )

    def _sync_transcribe(
        self,
        audio: np.ndarray,
        duration: float,
        language: Optional[str],
        with_timestamps: bool,
    ) -> TranscriptionResponse:
        target_lang = language if language in VALID_LANGUAGES else None
        prompt = INITIAL_PROMPTS.get(target_lang or "", None)

        segments_gen, info = self.model.transcribe(
            audio,
            beam_size=5,
            language=target_lang,
            initial_prompt=prompt,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=250),
        )

        detected_lang = target_lang or (info.language if info else "en")
        if detected_lang not in VALID_LANGUAGES:
            detected_lang = "en"

        raw_segments = list(segments_gen)

        # Check if Whisper detected no speech
        if len(raw_segments) == 0:
            return TranscriptionResponse(
                transcript="",
                language=detected_lang,
                confidence=None,
                duration=round(duration, 3),
                no_speech=True,
                segments=[],
            )

        full_text_parts = []
        segments_list: list[Segment] = []
        logprobs = []

        for seg in raw_segments:
            seg_text = seg.text.strip()
            if seg_text:
                full_text_parts.append(seg_text)
                if with_timestamps:
                    segments_list.append(
                        Segment(
                            text=seg_text,
                            start=round(float(seg.start), 3),
                            end=round(float(seg.end), 3),
                        )
                    )
                if hasattr(seg, "avg_logprob") and seg.avg_logprob is not None:
                    logprobs.append(seg.avg_logprob)

        full_text = " ".join(full_text_parts).strip()

        if not full_text:
            return TranscriptionResponse(
                transcript="",
                language=detected_lang,
                confidence=None,
                duration=round(duration, 3),
                no_speech=True,
                segments=[],
            )

        avg_logprob = float(np.mean(logprobs)) if logprobs else -0.2
        confidence = round(max(0.0, min(1.0, math.exp(avg_logprob))), 3)

        return TranscriptionResponse(
            transcript=full_text,
            language=detected_lang,
            confidence=confidence,
            duration=round(duration, 3),
            no_speech=False,
            segments=segments_list,
        )

