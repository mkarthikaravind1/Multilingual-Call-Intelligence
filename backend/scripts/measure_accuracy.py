"""Measure the system against the SRD's accuracy targets.

For each test call, put a label file in a folder, and its recording beside it
with the same name (the recording is needed for the transcription score only):

    eval/call_01.json    eval/call_01.wav     (or .mp3, .m4a, .ogg, .flac)

A label file says what a careful listener hears on the call (a template is
in scripts/accuracy_label_template.json):

    {
      "transcript": "ICR: Good morning, how can I help?\\nCUSTOMER: My car was due yesterday.",
      "categories": ["Cost", "Turnaround Time"],
      "sentiment": "FRUSTRATED"
    }

Start each line of the transcript with who says it (ICR: or CUSTOMER:), so
the analysis knows whose words they are, as it does on a real call. Without
those, everything is taken as the customer's.

Then, from backend/ (this uses the real speech recogniser and LLM in .env, so
it costs Sarvam credits and LLM requests):

    python -m scripts.measure_accuracy eval/ --report accuracy-report.md

With --skip-asr the recordings are not needed: the label's transcript is
analysed as it is, which measures the classification and the sentiment on
their own (and leaves speech recognition unmeasured).

What is scored, and against which SRD target:

    Speech recognition (95%)     1 - word error rate over all calls, the call
                                 transcribed as a live call is. Character
                                 accuracy is shown too: it is the fairer
                                 figure for Tamil and the other Indian
                                 languages, whose words are long.
    Complaint categories (92%)   Of every category that was expected or
                                 detected, the share that was both.
    Several categories (88%)     Of the calls with two or more expected
                                 categories, the share where all were detected.
    Sentiment (90%)              The share of calls given the expected label.
    Question relevance (85%)     With --question-outcomes: of the suggested
                                 questions executives accepted or skipped in
                                 the database, the share accepted. The SRD
                                 asks for a human rating; this is the nearest
                                 thing the system records.

The SRD's speed targets (transcript within 2 s, categories within 3 s, a
question within 1.5 s) are not measured here.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.conversation import Conversation
from app.domain.sentiment import SentimentLabel
from app.domain.utterance import SpeakerRole, Utterance
from scripts.evaluate_transcription import Score, load_pcm, score, transcribe_live

AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".ogg", ".flac")
# A rate over fewer than this many questions says little.
MIN_QUESTION_OUTCOMES = 30

TARGETS = {
    "speech": 0.95,
    "categories": 0.92,
    "multi_category": 0.88,
    "sentiment": 0.90,
    "questions": 0.85,
}


class LabelError(ValueError):
    pass


@dataclass(frozen=True)
class Label:
    name: str
    transcript: str
    categories: frozenset[str]
    sentiment: SentimentLabel | None
    recording: Path | None = None


@dataclass(frozen=True)
class CallResult:
    """What the system made of one labelled call."""

    label: Label
    detected: frozenset[str]
    sentiment: SentimentLabel | None
    # None when speech recognition was not run.
    transcription: Score | None = None


@dataclass(frozen=True)
class Measure:
    """One SRD target: the share reached, or None when it could not be
    measured (the note says why)."""

    name: str
    target: float
    correct: int = 0
    total: int = 0
    note: str = ""
    extra: tuple[str, ...] = field(default=())

    @property
    def rate(self) -> float | None:
        return None if self.total == 0 else self.correct / self.total

    @property
    def verdict(self) -> str:
        if self.rate is None:
            return "not measured"
        return "meets the target" if self.rate >= self.target else "below the target"


def _category_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def load_label(path: Path, known_categories: dict[str, str] | None = None) -> Label:
    """known_categories: the spelling of each category the system has, by
    its name in lower case; a label naming another one is a mistake."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LabelError(f"{path.name}: not valid JSON ({error.msg}, line {error.lineno}).")
    if not isinstance(data, dict):
        raise LabelError(f"{path.name}: must be a JSON object.")

    transcript = data.get("transcript", "")
    if not isinstance(transcript, str):
        raise LabelError(f"{path.name}: \"transcript\" must be text.")
    categories = data.get("categories", [])
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        raise LabelError(f"{path.name}: \"categories\" must be a list of names.")
    names = set()
    for category in categories:
        if known_categories is None:
            names.add(" ".join(category.split()))
        elif _category_key(category) in known_categories:
            names.add(known_categories[_category_key(category)])
        else:
            raise LabelError(
                f"{path.name}: {category!r} is not a complaint category. "
                f"The categories are: {', '.join(sorted(known_categories.values()))}."
            )

    sentiment = data.get("sentiment")
    if sentiment is not None:
        try:
            sentiment = SentimentLabel(str(sentiment).strip().upper())
        except ValueError:
            raise LabelError(
                f"{path.name}: \"sentiment\" must be one of "
                f"{', '.join(label.value for label in SentimentLabel)}."
            )
    recording = next(
        (path.with_suffix(suffix) for suffix in AUDIO_SUFFIXES if path.with_suffix(suffix).exists()),
        None,
    )
    return Label(path.stem, transcript.strip(), frozenset(names), sentiment, recording)


def measures(
    results: list[CallResult], question_outcomes: tuple[int, int] | None = None
) -> list[Measure]:
    """Each SRD accuracy target against what the system produced."""
    transcribed = [r.transcription for r in results if r.transcription is not None]
    if transcribed:
        total = sum(transcribed, Score(0, 0, 0, 0))
        speech = Measure(
            "Speech recognition (words right)",
            TARGETS["speech"],
            max(0, total.words - total.word_errors),
            total.words,
            extra=(f"characters right: {max(0.0, 1 - total.cer):.1%}",),
        )
    else:
        speech = Measure(
            "Speech recognition (words right)",
            TARGETS["speech"],
            note="No call was transcribed (no recording, no transcript in its label, or --skip-asr).",
        )

    both = sum(len(r.label.categories & r.detected) for r in results)
    either = sum(len(r.label.categories | r.detected) for r in results)
    missed = sum(len(r.label.categories - r.detected) for r in results)
    extra = sum(len(r.detected - r.label.categories) for r in results)
    categories = Measure(
        "Complaint categories",
        TARGETS["categories"],
        both,
        either,
        note="" if either else "No call had an expected or a detected category.",
        extra=(f"missed: {missed}", f"detected but not expected: {extra}"),
    )

    several = [r for r in results if len(r.label.categories) >= 2]
    multi = Measure(
        "Several categories on one call",
        TARGETS["multi_category"],
        sum(1 for r in several if r.label.categories <= r.detected),
        len(several),
        note="" if several else "No labelled call has two or more categories.",
    )

    labelled = [r for r in results if r.label.sentiment is not None]
    sentiment = Measure(
        "Sentiment",
        TARGETS["sentiment"],
        sum(1 for r in labelled if r.sentiment is r.label.sentiment),
        len(labelled),
        note="" if labelled else "No label gives a sentiment.",
        extra=(
            "right side (negative or not): "
            + str(
                sum(
                    1
                    for r in labelled
                    if r.sentiment is not None
                    and r.sentiment.is_negative == r.label.sentiment.is_negative
                )
            )
            + f" of {len(labelled)}",
        )
        if labelled
        else (),
    )

    if question_outcomes is None:
        questions = Measure(
            "Question relevance (accepted by executives)",
            TARGETS["questions"],
            note="Not asked for (--question-outcomes reads it from the database).",
        )
    else:
        accepted, skipped = question_outcomes
        if accepted + skipped < MIN_QUESTION_OUTCOMES:
            questions = Measure(
                "Question relevance (accepted by executives)",
                TARGETS["questions"],
                note=(
                    f"Not enough data yet: {accepted + skipped} questions were accepted or "
                    f"skipped, and at least {MIN_QUESTION_OUTCOMES} are needed."
                ),
            )
        else:
            questions = Measure(
                "Question relevance (accepted by executives)",
                TARGETS["questions"],
                accepted,
                accepted + skipped,
            )
    return [speech, categories, multi, sentiment, questions]


def report(results: list[CallResult], rows: list[Measure]) -> str:
    """The measurement as a Markdown document."""
    lines = [
        "# Accuracy against the SRD targets",
        "",
        f"{len(results)} labelled calls.",
        "",
        "| Target | SRD asks for | Measured | Out of | Result |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        measured = "-" if row.rate is None else f"{row.rate:.1%}"
        out_of = "-" if row.rate is None else f"{row.correct} of {row.total}"
        lines.append(
            f"| {row.name} | {row.target:.0%} | {measured} | {out_of} | {row.verdict} |"
        )
    notes = [(row.name, row.note) for row in rows if row.note]
    notes += [(row.name, "; ".join(row.extra)) for row in rows if row.extra and row.rate is not None]
    if notes:
        lines += ["", "## Notes", ""] + [f"- **{name}:** {note}" for name, note in notes]

    lines += [
        "",
        "## Each call",
        "",
        "| Call | Words right | Expected categories | Detected | Sentiment expected | Sentiment given |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        words = (
            "-"
            if result.transcription is None
            else f"{max(0.0, 1 - result.transcription.wer):.1%}"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    result.label.name,
                    words,
                    ", ".join(sorted(result.label.categories)) or "none",
                    ", ".join(sorted(result.detected)) or "none",
                    "-" if result.label.sentiment is None else result.label.sentiment.value,
                    "-" if result.sentiment is None else result.sentiment.value,
                ]
            )
            + " |"
        )
    lines += [
        "",
        "The SRD's speed targets (transcript within 2 s, categories within 3 s, a question "
        "within 1.5 s) are not measured here.",
        "",
    ]
    return "\n".join(lines)


_SPEAKERS = {"icr": SpeakerRole.ICR, "executive": SpeakerRole.ICR, "customer": SpeakerRole.CUSTOMER}


def spoken_lines(transcript: str) -> list[tuple[SpeakerRole, str]]:
    """The transcript as (speaker, words): a line starting "ICR:" or
    "CUSTOMER:" is that speaker's, and a line without one carries on the
    line before (the customer's when there is none)."""
    lines: list[tuple[SpeakerRole, str]] = []
    for raw in transcript.splitlines():
        text = raw.strip()
        if not text:
            continue
        name, colon, rest = text.partition(":")
        role = _SPEAKERS.get(name.strip().casefold()) if colon else None
        if role is not None:
            if rest.strip():
                lines.append((role, rest.strip()))
        elif lines:
            lines[-1] = (lines[-1][0], f"{lines[-1][1]} {text}")
        else:
            lines.append((SpeakerRole.CUSTOMER, text))
    return lines


def without_speakers(transcript: str) -> str:
    """Only the words, for comparing with what speech recognition heard."""
    return " ".join(text for _, text in spoken_lines(transcript))


def conversation_of(name: str, transcript: str) -> Conversation:
    """The call as the analysis is given it."""
    conversation = Conversation(call_id=f"accuracy-{name}")
    for index, (role, text) in enumerate(spoken_lines(transcript)):
        conversation.add_utterance(
            Utterance(
                utterance_id=f"u{index + 1}",
                transcript=text,
                speaker_role=role,
                languages=("en",),
                start_time=float(index),
                end_time=index + 0.5,
            )
        )
    return conversation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", type=Path, help="label files (.json), recordings beside them")
    parser.add_argument("--skip-asr", action="store_true", help="analyse each label's transcript")
    parser.add_argument("--sample-rate", type=int, default=16000, choices=(8000, 16000))
    parser.add_argument(
        "--question-outcomes",
        action="store_true",
        help="read how many suggested questions were accepted or skipped from the database",
    )
    parser.add_argument("--report", type=Path, help="write the report to this Markdown file")
    args = parser.parse_args(argv)

    # Imported here: only a real run needs the providers and their keys.
    from app.composition.providers import (
        create_asr_provider,
        create_complaint_provider,
        create_llm_client,
        create_sentiment_provider,
    )
    from app.core.config import get_settings
    from app.services.complaint_category_catalog import BUILT_IN_CATALOG
    from app.services.language_lock import LanguageLock

    known = {_category_key(name): name for name in BUILT_IN_CATALOG.names()}
    try:
        labels = [load_label(path, known) for path in sorted(args.folder.glob("*.json"))]
    except LabelError as error:
        print(error, file=sys.stderr)
        return 1
    if not labels:
        print(f"No label files (.json) in {args.folder}.", file=sys.stderr)
        return 1

    settings = get_settings()
    llm = create_llm_client(settings)
    complaints = create_complaint_provider(llm, settings)
    sentiment = create_sentiment_provider(llm, settings)
    asr = None if args.skip_asr else create_asr_provider(settings)

    results = []
    for label in labels:
        transcription, said = None, label.transcript
        if asr is not None and label.recording is not None:
            said, _ = transcribe_live(
                asr,
                load_pcm(label.recording, args.sample_rate),
                args.sample_rate,
                LanguageLock(settings.asr_language_lock_after, settings.asr_language_unlock_after),
            )
            if label.transcript:
                transcription = score(without_speakers(label.transcript), said)
        if not said.strip():
            print(f"{label.name}: nothing to analyse (no transcript and no recording); skipped.")
            continue
        conversation = conversation_of(label.name, said)
        detected = frozenset(d.category for d in complaints.detect(conversation))
        given = sentiment.analyze(conversation).label
        results.append(CallResult(label, detected, given, transcription))
        print(f"{label.name}: {', '.join(sorted(detected)) or 'no complaints'}; {given.value}")

    outcomes = None
    if args.question_outcomes:
        from app.composition.database import build_production_repositories

        outcomes = build_production_repositories(settings).question_outcome.totals()

    text = report(results, measures(results, outcomes))
    print()
    print(text)
    if args.report is not None:
        args.report.write_text(text, encoding="utf-8")
        print(f"Written to {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
