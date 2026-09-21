import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from app.ai.asr.provider import ASRProvider
from app.ai.language.provider import LanguageIdentificationProvider
from app.ai.llm.client import LLMClient
from app.ai.speaker.provider import DiarizedSegment
from app.composition.providers import UnsupportedProviderError
from app.composition.services import (
    build_audio_processing_pipeline,
    build_call_service,
    build_call_workflow_service,
)
from app.core.config import Settings
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.utterance import Utterance
from app.services.audio_ingestion_service import (
    AudioIngestionError,
    AudioIngestionService,
)
from app.services.audio_processing_pipeline import AudioPipelineError
from app.services.call_workflow_service import CallAnalysisResult

DEV_CALL_ID = "dev-call"
DEV_SPEAKER_ID = "speaker_0"


@dataclass(frozen=True)
class RunnerOutput:
    utterance: Utterance
    analysis: CallAnalysisResult


def build_dev_settings() -> Settings:
    return Settings(diarization_provider="scripted", role_provider="order_based")


def run_audio_file(
    path: str | Path,
    settings: Settings | None = None,
    *,
    asr_provider: ASRProvider | None = None,
    language_provider: LanguageIdentificationProvider | None = None,
    llm_client: LLMClient | None = None,
    call_id: str = DEV_CALL_ID,
) -> RunnerOutput:
    ingested = AudioIngestionService().load_wav(path)
    settings = settings or build_dev_settings()

    call_service = build_call_service()
    workflow = build_call_workflow_service(
        settings=settings, llm_client=llm_client, call_service=call_service
    )
    pipeline = build_audio_processing_pipeline(
        workflow,
        [DiarizedSegment(DEV_SPEAKER_ID, 0.0, ingested.metadata.duration_seconds)],
        settings=settings,
        asr_provider=asr_provider,
        language_provider=language_provider,
    )

    call_service.start_call(call_id)
    analysis = pipeline.process_audio(call_id, ingested.audio)

    utterance = call_service.get_call(call_id).latest_utterance
    if utterance is None:
        raise AudioPipelineError("No utterance was produced.")
    return RunnerOutput(utterance=utterance, analysis=analysis)


def format_report(output: RunnerOutput) -> str:
    utterance = output.utterance
    analysis = output.analysis

    lines = [
        f"Transcript: {utterance.transcript}",
        f"Language: {', '.join(utterance.languages)}",
        f"Speaker role: {utterance.speaker_role.value}",
        "Complaint coverage:",
    ]

    coverage_lines = []
    for category in COMPLAINT_CATEGORIES:
        complaint = analysis.coverage.get(category)
        if complaint is not None:
            coverage_lines.append(f"  {category}: {complaint.status.value}")
    lines.extend(coverage_lines or ["  none"])

    sentiment = analysis.sentiment
    lines.append(
        f"Sentiment: {sentiment.label.value} (confidence: {sentiment.confidence})"
    )
    lines.append(f"  Evidence: {sentiment.evidence}")

    suggestion = analysis.question_suggestion
    if suggestion is None:
        lines.append("Next question: none")
    else:
        lines.extend(
            [
                f"Next question: {suggestion.question}",
                f"  Target category: {suggestion.target_category}",
                f"  Priority: {suggestion.priority}",
                f"  Reason: {suggestion.reason}",
                f"  Source: {suggestion.source.value}",
            ]
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Development-only end-to-end audio runner."
    )
    parser.add_argument("wav_path", type=Path, help="Path to a WAV file.")
    args = parser.parse_args(argv)

    try:
        output = run_audio_file(args.wav_path)
    except (AudioIngestionError, AudioPipelineError, UnsupportedProviderError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(format_report(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())