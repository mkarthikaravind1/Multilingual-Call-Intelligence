"""Measure transcription accuracy (WER and CER) against reference transcripts.

Put each test recording next to its correct transcript, with the same name:

    eval/call_01.wav   eval/call_01.txt
    eval/call_02.mp3   eval/call_02.txt   (non-WAV needs ffmpeg)

then run, from backend/ (calls the real ASR in .env: this costs Sarvam credits):

    python -m scripts.evaluate_transcription eval/

Each recording is transcribed four ways, so the improvements can be told apart:

    baseline   live chunks as before: 8 kHz mu-law, chunks from 1.5 s of speech,
               language guessed every chunk
    live       live chunks at --sample-rate, with the language lock
    post       the whole call again in long windows, in the locked language
               (what POST_CALL_RETRANSCRIPTION_ENABLED keeps after the call)

WER counts word mistakes; CER counts character mistakes, which is fairer for
Tamil, where one long word carries what English says in several. Both are
lower-is-better. The recording should hold one speaker, or both sides mixed;
the reference is the plain text of everything said, in the script it should
be written in (code-mixed English words in Latin letters, as Sarvam's codemix
mode writes them).
"""

import argparse
import audioop
import io
import re
import shutil
import subprocess
import sys
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path

from app.ai.asr.provider import ASRProvider, NoSpeechDetected
from app.composition.providers import create_asr_provider
from app.core.config import get_settings
from app.services.language_lock import LanguageLock
from app.services.post_call_retranscription import _speech_windows, _wav
from app.services.telephony_audio_buffer import TelephonyAudioBuffer

_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
_FRAME_SECONDS = 0.02
_BASELINE_MIN_SPEECH_SECONDS = 1.5


@dataclass(frozen=True)
class Score:
    word_errors: int
    words: int
    char_errors: int
    chars: int

    @property
    def wer(self) -> float:
        return self.word_errors / max(self.words, 1)

    @property
    def cer(self) -> float:
        return self.char_errors / max(self.chars, 1)

    def __add__(self, other: "Score") -> "Score":
        return Score(
            self.word_errors + other.word_errors,
            self.words + other.words,
            self.char_errors + other.char_errors,
            self.chars + other.chars,
        )


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold()
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    return re.sub(r"\s+", " ", text).strip()


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        current = [i]
        for j, hyp in enumerate(hypothesis, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref != hyp))
            )
        previous = current
    return previous[-1]


def score(reference: str, hypothesis: str) -> Score:
    ref, hyp = normalize(reference), normalize(hypothesis)
    ref_chars, hyp_chars = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    return Score(
        edit_distance(ref.split(), hyp.split()),
        len(ref.split()),
        edit_distance(ref_chars, hyp_chars),
        len(ref_chars),
    )


def load_pcm(path: Path, sample_rate: int) -> bytes:
    """16-bit mono PCM at sample_rate."""
    if path.suffix.lower() != ".wav":
        if shutil.which("ffmpeg") is None:
            raise SystemExit(f"{path.name}: install ffmpeg to read non-WAV files.")
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sample_rate),
             "-f", "s16le", "-"],
            capture_output=True,
            check=True,
        )
        return result.stdout
    with wave.open(str(path)) as source:
        width, channels, rate = source.getsampwidth(), source.getnchannels(), source.getframerate()
        pcm = source.readframes(source.getnframes())
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if channels == 2:
        pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
    elif channels != 1:
        raise SystemExit(f"{path.name}: only mono or stereo WAV files are supported.")
    if rate != sample_rate:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, sample_rate, None)
    return pcm


def phone_line(pcm: bytes, sample_rate: int) -> bytes:
    """The audio as an 8 kHz mu-law phone line carries it, back at 8 kHz PCM."""
    narrow, _ = audioop.ratecv(pcm, 2, 1, sample_rate, 8000, None)
    return audioop.ulaw2lin(audioop.lin2ulaw(narrow, 2), 2)


def _transcribe(asr: ASRProvider, audio: bytes, hint: str | None) -> tuple[str, str | None]:
    try:
        if hint is None or not asr.supports_language_hint:
            result = asr.transcribe(audio)
        else:
            result = asr.transcribe(audio, language_hint=hint)
    except NoSpeechDetected:
        return "", None
    return result.transcript, result.detected_language


def transcribe_live(
    asr: ASRProvider,
    pcm: bytes,
    sample_rate: int,
    lock: LanguageLock | None,
    min_speech_seconds: float | None = None,
) -> tuple[str, str | None]:
    """As a live call is: cut into chunks at pauses, each transcribed alone.
    Returns the transcript and the language the lock settled on."""
    settings = get_settings()
    buffer = TelephonyAudioBuffer(
        sample_rate=sample_rate,
        flush_after_seconds=settings.plivo_stream_flush_seconds,
        pause_seconds=settings.plivo_stream_pause_seconds,
        min_speech_seconds=(
            settings.plivo_stream_min_speech_seconds
            if min_speech_seconds is None
            else min_speech_seconds
        ),
        silence_rms=settings.plivo_stream_silence_rms,
    )
    frame = int(sample_rate * _FRAME_SECONDS) * 2
    texts: list[str] = []

    def transcribe_chunk(force: bool) -> None:
        chunk = buffer.flush(force=force)
        if chunk is None or not chunk.has_speech:
            return
        hint = None if lock is None else lock.hint(None)
        text, language = _transcribe(asr, chunk.audio, hint)
        if lock is not None:
            if language is None:
                lock.observe_no_speech(None)
            else:
                lock.observe(None, language)
        if text.strip():
            texts.append(text.strip())

    for offset in range(0, len(pcm), frame):
        buffer.accept(None, pcm[offset : offset + frame])
        if buffer.should_flush():
            transcribe_chunk(force=False)
    transcribe_chunk(force=True)
    return " ".join(texts), None if lock is None else lock.hint(None)


def transcribe_post(
    asr: ASRProvider, pcm: bytes, sample_rate: int, hint: str | None, window_seconds: float
) -> str:
    settings = get_settings()
    texts = []
    for start, end in _speech_windows(
        pcm, sample_rate, window_seconds, settings.plivo_stream_silence_rms
    ):
        text, _ = _transcribe(asr, _wav(pcm[start:end], sample_rate), hint)
        if text.strip():
            texts.append(text.strip())
    return " ".join(texts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", type=Path, help="recordings with matching .txt references")
    parser.add_argument("--sample-rate", type=int, default=16000, choices=(8000, 16000))
    parser.add_argument("--window-seconds", type=float, default=25.0)
    parser.add_argument(
        "--language", help="tell the post-call pass this language instead of the locked one"
    )
    parser.add_argument("--show-text", action="store_true", help="print each transcript")
    args = parser.parse_args(argv)

    recordings = sorted(
        p for p in args.folder.iterdir()
        if p.suffix.lower() in _AUDIO_SUFFIXES and p.with_suffix(".txt").exists()
    )
    if not recordings:
        print(f"No recordings with a matching .txt reference in {args.folder}.", file=sys.stderr)
        return 1

    settings = get_settings()
    asr = create_asr_provider(settings)
    modes = ("baseline", "live", "post")
    totals = {mode: Score(0, 0, 0, 0) for mode in modes}

    print(f"{'recording':30} " + " ".join(f"{m + ' WER/CER':>18}" for m in modes))
    for path in recordings:
        reference = path.with_suffix(".txt").read_text(encoding="utf-8")
        pcm = load_pcm(path, args.sample_rate)

        baseline, _ = transcribe_live(
            asr, phone_line(pcm, args.sample_rate), 8000, None, _BASELINE_MIN_SPEECH_SECONDS
        )
        live, locked = transcribe_live(
            asr,
            pcm,
            args.sample_rate,
            LanguageLock(settings.asr_language_lock_after, settings.asr_language_unlock_after),
        )
        post = transcribe_post(
            asr, pcm, args.sample_rate, args.language or locked, args.window_seconds
        )

        texts = {"baseline": baseline, "live": live, "post": post}
        scores = {mode: score(reference, texts[mode]) for mode in modes}
        for mode in modes:
            totals[mode] += scores[mode]
        print(
            f"{path.name[:30]:30} "
            + " ".join(f"{s.wer:>8.1%} / {s.cer:<7.1%}" for s in scores.values())
            + f"  (locked: {locked or '-'})"
        )
        if args.show_text:
            for mode in modes:
                print(f"    {mode:8} {texts[mode]}")

    print(
        f"{'ALL':30} " + " ".join(f"{s.wer:>8.1%} / {s.cer:<7.1%}" for s in totals.values())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
