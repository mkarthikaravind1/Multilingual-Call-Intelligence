import wave
from pathlib import Path

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.sentiment.provider import SentimentResult
from app.core.config import Settings
from app.domain.utterance import SpeakerRole
from scripts import run_audio_pipeline as runner


class FakeLLMClient(LLMClient):
    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text="[]")


class FakeASRProvider(ASRProvider):
    def transcribe(self, audio: bytes) -> ASRResult:
        return ASRResult(
            transcript="The bill is too high",
            detected_language="en",
            start_time=0.0,
            end_time=2.0,
        )


class FakeLanguageProvider(LanguageIdentificationProvider):
    def identify(self, text: str) -> LanguageIdentificationResult:
        return LanguageIdentificationResult(languages=[LanguageSpan(language="en")])


def write_wav(path: Path, frames: int = 8000, sample_rate: int = 8000) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00" * frames * 2)
    return path


def make_settings() -> Settings:
    return Settings(
        _env_file=None, # type: ignore
        diarization_provider="scripted",
        role_provider="order_based",
    )


def run_with_fakes(path: Path) -> runner.RunnerOutput:
    return runner.run_audio_file(
        path,
        make_settings(),
        asr_provider=FakeASRProvider(),
        language_provider=FakeLanguageProvider(),
        llm_client=FakeLLMClient(),
    )


def test_run_audio_file_processes_wav_through_pipeline(tmp_path):
    output = run_with_fakes(write_wav(tmp_path / "call.wav"))

    assert output.utterance.transcript == "The bill is too high"
    assert output.utterance.languages == ("en",)
    assert output.utterance.speaker_role == SpeakerRole.ICR
    assert output.analysis.coverage.call_id == runner.DEV_CALL_ID
    assert isinstance(output.analysis.sentiment, SentimentResult)
    assert output.analysis.question_suggestion is None


def test_format_report_includes_all_sections(tmp_path):
    report = runner.format_report(run_with_fakes(write_wav(tmp_path / "call.wav")))

    assert "Transcript: The bill is too high" in report
    assert "Language: en" in report
    assert "Speaker role: ICR" in report
    assert "Complaint coverage:" in report
    assert "Sentiment:" in report
    assert "Next question: none" in report


def test_main_prints_report_and_returns_zero(tmp_path, monkeypatch, capsys):
    output = run_with_fakes(write_wav(tmp_path / "call.wav"))
    monkeypatch.setattr(runner, "run_audio_file", lambda path: output)

    exit_code = runner.main([str(tmp_path / "call.wav")])

    assert exit_code == 0
    assert "Transcript: The bill is too high" in capsys.readouterr().out


def test_main_reports_missing_file_and_returns_one(tmp_path, capsys):
    exit_code = runner.main([str(tmp_path / "missing.wav")])

    assert exit_code == 1
    assert "not found" in capsys.readouterr().err