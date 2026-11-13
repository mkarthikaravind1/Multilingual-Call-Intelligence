"""ASR Error Metrics: WER, CER, Words Right, Latency, and RTF."""

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, TypeVar, Union

T = TypeVar("T")


def edit_distance(ref: Sequence[T], hyp: Sequence[T]) -> int:
    """Compute standard Levenshtein edit distance using dynamic programming."""
    n = len(ref)
    m = len(hyp)
    if n == 0:
        return m
    if m == 0:
        return n

    # Use single row DP
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            temp = dp[j]
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[j] = min(
                dp[j] + 1,        # deletion
                dp[j - 1] + 1,    # insertion
                prev + cost       # substitution
            )
            prev = temp
    return dp[m]


def compute_wer(reference: str, hypothesis: str) -> float:
    """Compute Word Error Rate (WER) between reference and hypothesis strings."""
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    dist = edit_distance(ref_words, hyp_words)
    return dist / len(ref_words)


def compute_cer(reference: str, hypothesis: str) -> float:
    """Compute Character Error Rate (CER) between reference and hypothesis strings."""
    ref_chars = list(reference.replace(" ", ""))
    hyp_chars = list(hypothesis.replace(" ", ""))
    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0
    dist = edit_distance(ref_chars, hyp_chars)
    return dist / len(ref_chars)


@dataclass
class ClipASRMetric:
    audio_file: str
    language: str
    reference_raw: str
    reference_norm: str
    hypothesis_raw: str
    hypothesis_norm: str
    wer: float
    cer: float
    words_right: float
    latency_sec: float
    audio_duration_sec: float
    rtf: float


@dataclass
class LanguageASRSummary:
    language: str
    total_clips: int = 0
    total_ref_words: int = 0
    total_word_errors: int = 0
    total_ref_chars: int = 0
    total_char_errors: int = 0
    total_latency: float = 0.0
    total_audio_duration: float = 0.0

    @property
    def wer(self) -> float:
        return (self.total_word_errors / self.total_ref_words) if self.total_ref_words > 0 else 0.0

    @property
    def cer(self) -> float:
        return (self.total_char_errors / self.total_ref_chars) if self.total_ref_chars > 0 else 0.0

    @property
    def words_right(self) -> float:
        return max(0.0, 1.0 - self.wer)

    @property
    def avg_latency_sec(self) -> float:
        return (self.total_latency / self.total_clips) if self.total_clips > 0 else 0.0

    @property
    def rtf(self) -> float:
        return (self.total_latency / self.total_audio_duration) if self.total_audio_duration > 0 else 0.0


def aggregate_asr_metrics(clip_metrics: List[ClipASRMetric]) -> Dict[str, LanguageASRSummary]:
    """Aggregate clip metrics by language plus an overall summary."""
    summaries: Dict[str, LanguageASRSummary] = {}

    def get_summary(lang: str) -> LanguageASRSummary:
        if lang not in summaries:
            summaries[lang] = LanguageASRSummary(language=lang)
        return summaries[lang]

    for m in clip_metrics:
        for key in (m.language, "OVERALL"):
            s = get_summary(key)
            s.total_clips += 1
            ref_words = m.reference_norm.split()
            hyp_words = m.hypothesis_norm.split()
            ref_chars = list(m.reference_norm.replace(" ", ""))
            hyp_chars = list(m.hypothesis_norm.replace(" ", ""))

            s.total_ref_words += len(ref_words)
            s.total_word_errors += edit_distance(ref_words, hyp_words)

            s.total_ref_chars += len(ref_chars)
            s.total_char_errors += edit_distance(ref_chars, hyp_chars)

            s.total_latency += m.latency_sec
            s.total_audio_duration += m.audio_duration_sec

    return summaries

