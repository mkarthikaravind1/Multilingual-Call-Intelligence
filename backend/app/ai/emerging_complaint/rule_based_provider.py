import hashlib
import re
from collections import defaultdict

from app.ai.emerging_complaint.provider import (
    CallComplaintRecord,
    EmergingComplaintDiscoveryProvider,
    EmergingComplaintDiscoveryRequest,
)
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.emerging_complaint_candidate import EmergingComplaintCandidate
from app.domain.utterance import SpeakerRole

# A normalized phrase shorter than this many words is treated as too
# generic/short (e.g. "ok", "thanks") to be a meaningful complaint pattern.
MIN_PHRASE_WORDS = 2

# A phrase must recur across at least this many distinct calls to count as
# "recurring" rather than a one-off remark.
MIN_RECURRING_CALLS = 2

_NORMALIZED_CATEGORIES = frozenset(category.casefold() for category in COMPLAINT_CATEGORIES)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(transcript: str) -> str:
    """Lowercases, strips punctuation, and collapses whitespace so that
    trivially different phrasing (case, punctuation, extra spaces) is
    treated as the same pattern. This is a purely lexical match, not a
    semantic one - that's the deliberate baseline for this milestone.
    """
    lowered = transcript.casefold()
    stripped = _NON_ALNUM_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def _stable_candidate_id(phrase: str) -> str:
    """Deterministic id derived from the normalized phrase, so the same
    detected pattern always gets the same id (required for stability
    within a request, and as a side effect, across repeated runs on the
    same input) instead of a random uuid.
    """
    digest = hashlib.sha256(phrase.encode("utf-8")).hexdigest()[:12]
    return f"emerging-{digest}"


def _proposed_name(phrase: str) -> str:
    return phrase.title()


def _description(phrase: str, distinct_call_count: int) -> str:
    return (
        f"Similar customer complaint phrasing observed across "
        f"{distinct_call_count} separate calls: \"{phrase}\"."
    )


class RuleBasedEmergingComplaintDiscoveryProvider(EmergingComplaintDiscoveryProvider):
    """Deterministic, LLM-free baseline for emerging-complaint discovery.

    Flags customer phrasing that recurs, verbatim after normalization,
    across two or more distinct calls and does not already correspond to
    a known complaint category. Purely lexical - two calls have to phrase
    the complaint the same way (modulo case/punctuation/whitespace) to be
    grouped together; no embeddings, clustering, or LLM involved. A later
    milestone can swap in a smarter provider behind the same interface
    without this one needing to change.
    """

    def discover(
        self, request: EmergingComplaintDiscoveryRequest
    ) -> tuple[EmergingComplaintCandidate, ...]:
        call_ids_by_phrase: dict[str, list[str]] = defaultdict(list)
        evidence_by_phrase: dict[str, list[str]] = defaultdict(list)

        for record in request.call_records:
            self._collect_phrases(record, call_ids_by_phrase, evidence_by_phrase)

        total_calls = len(request.call_records)
        candidates = []
        for phrase in sorted(call_ids_by_phrase):
            call_ids = call_ids_by_phrase[phrase]
            distinct_call_ids = sorted(set(call_ids))
            if len(distinct_call_ids) < MIN_RECURRING_CALLS:
                continue

            confidence = min(1.0, len(distinct_call_ids) / total_calls)

            candidates.append(
                EmergingComplaintCandidate(
                    candidate_id=_stable_candidate_id(phrase),
                    proposed_name=_proposed_name(phrase),
                    description=_description(phrase, len(distinct_call_ids)),
                    evidence=tuple(evidence_by_phrase[phrase]),
                    occurrence_count=len(call_ids),
                    confidence=confidence,
                )
            )

        return tuple(candidates)

    def _collect_phrases(
        self,
        record: CallComplaintRecord,
        call_ids_by_phrase: dict[str, list[str]],
        evidence_by_phrase: dict[str, list[str]],
    ) -> None:
        for utterance in record.utterances:
            if utterance.speaker_role != SpeakerRole.CUSTOMER:
                continue

            normalized = _normalize(utterance.transcript)

            # An existing category, however phrased, is not "emerging".
            if normalized in _NORMALIZED_CATEGORIES:
                continue

            if len(normalized.split()) < MIN_PHRASE_WORDS:
                continue

            call_ids_by_phrase[normalized].append(record.call_id)
            evidence_by_phrase[normalized].append(utterance.transcript)