from typing import Optional
from app.config import get_settings
from app.engine.base import BaseSTTEngine
from app.engine.fake import FakeSTTEngine
from app.engine.faster_whisper import FasterWhisperEngine
from app.engine.indic_conformer import IndicConformerEngine

_engine_instance: Optional[BaseSTTEngine] = None


def get_engine() -> BaseSTTEngine:
    global _engine_instance
    if _engine_instance is None:
        settings = get_settings()
        backend = (settings.MODEL_BACKEND or "faster-whisper").lower()

        if backend == "fake":
            _engine_instance = FakeSTTEngine(
                model_name=settings.MODEL_NAME_OR_PATH,
                device="cpu",
                loaded=True,
            )
        elif backend == "indic-conformer":
            _engine_instance = IndicConformerEngine(
                model_name_or_path=settings.MODEL_NAME_OR_PATH,
                device=settings.DEVICE,
                compute_type=settings.COMPUTE_TYPE,
                max_concurrent=settings.MAX_CONCURRENT_TRANSCRIPTIONS,
            )
        else:
            # Default to faster-whisper
            _engine_instance = FasterWhisperEngine(
                model_name_or_path=settings.MODEL_NAME_OR_PATH,
                device=settings.DEVICE,
                compute_type=settings.COMPUTE_TYPE,
                max_concurrent=settings.MAX_CONCURRENT_TRANSCRIPTIONS,
            )
    return _engine_instance


def set_engine(engine: Optional[BaseSTTEngine]) -> None:
    """Sets or overrides the global STT engine (useful for testing)."""
    global _engine_instance
    _engine_instance = engine

