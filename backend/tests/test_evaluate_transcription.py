import math
import struct
import wave

from app.ai.asr.provider import ASRProvider, ASRResult
from scripts import evaluate_transcription as evaluation


def test_scores_ignore_case_punctuation_and_spacing():
    result = evaluation.score("Brake  pad, மாற்ற வேண்டும்.", "brake pad மாற்ற வேணும்")

    assert (result.word_errors, result.words) == (1, 4)
    assert result.wer == 0.25
    assert 0 < result.cer < 0.25


def test_perfect_and_empty_transcripts():
    assert evaluation.score("வணக்கம் சார்", "வணக்கம் சார்").wer == 0
    assert evaluation.score("வணக்கம் சார்", "").wer == 1


class EchoASR(ASRProvider):
    supports_language_hint = True

    def __init__(self) -> None:
        self.hints = []

    def transcribe(self, audio, language_hint=None):
        self.hints.append(language_hint)
        return ASRResult("வணக்கம்", "ta", 0.0, 1.0, None)


def _speech(seconds: float, rate: int) -> bytes:
    tone = b"".join(struct.pack("<h", int(8000 * math.sin(i / 5))) for i in range(int(rate * seconds)))
    return tone + b"\x00\x00" * rate  # then 1 s of silence


def test_live_simulation_locks_the_language(tmp_path):
    asr = EchoASR()
    pcm = _speech(3, 16000) * 3

    text, locked = evaluation.transcribe_live(
        asr, pcm, 16000, evaluation.LanguageLock(lock_after=2)
    )

    # How many chunks depends on the chunk settings in .env.
    assert set(text.split()) == {"வணக்கம்"}
    assert locked == "ta"
    assert asr.hints[:2] == [None, None]
    assert set(asr.hints[2:]) == {"ta"}


def test_wav_is_read_as_mono_at_the_wanted_rate(tmp_path):
    path = tmp_path / "call.wav"
    with wave.open(str(path), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(8000)
        target.writeframes(b"\x01\x00" * 2 * 8000)

    pcm = evaluation.load_pcm(path, 16000)

    assert abs(len(pcm) - 2 * 16000) <= 4
