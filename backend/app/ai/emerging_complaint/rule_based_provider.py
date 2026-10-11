import hashlib
import re
from dataclasses import dataclass, field

from app.ai.emerging_complaint.provider import (
    CallComplaintRecord,
    EmergingComplaintDiscoveryProvider,
    EmergingComplaintDiscoveryRequest,
)
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.complaint_category import MAX_CUSTOM_CATEGORY_NAME_LENGTH
from app.domain.emerging_complaint_candidate import EmergingComplaintCandidate
from app.domain.utterance import SpeakerRole, Utterance

# A normalized phrase shorter than this many words is treated as too
# generic/short (e.g. "ok", "thanks") to be a meaningful complaint pattern.
MIN_PHRASE_WORDS = 2

# A phrase must recur across at least this many distinct calls to count as
# "recurring" rather than a one-off remark.
MIN_RECURRING_CALLS = 2

_NORMALIZED_CATEGORIES = frozenset(category.casefold() for category in COMPLAINT_CATEGORIES)
# The category for a complaint that fits none of the others: a line under
# it is exactly what a new theme is made of.
_CATCH_ALL = "other"

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
    """The opening words of the phrase, short enough to become a category
    name as it stands."""
    name = ""
    for word in phrase.title().split():
        longer = f"{name} {word}".strip()
        if len(longer) > MAX_CUSTOM_CATEGORY_NAME_LENGTH - 1:
            return f"{name}…" if name else word[: MAX_CUSTOM_CATEGORY_NAME_LENGTH]
        name = longer
    return name


def _description(distinct_call_count: int) -> str:
    return f"Customers said this, in the same words, on {distinct_call_count} separate calls."


@dataclass
class _Phrase:
    """One wording and where customers used it."""

    call_ids: list[str] = field(default_factory=list)
    # Each way it was written down, once.
    quotes: list[str] = field(default_factory=list)
    # The AI put a line with this wording under an existing category.
    categorised: bool = False
    # The AI rated a line with this wording, and found it unhappy at least once.
    rated: bool = False
    unhappy: bool = False

    def add(self, call_id: str, utterance: Utterance) -> None:
        self.call_ids.append(call_id)
        if utterance.transcript not in self.quotes:
            self.quotes.append(utterance.transcript)
        categories = {category.casefold() for category in utterance.complaint_categories}
        if categories - {_CATCH_ALL}:
            self.categorised = True
        elif categories:
            self.unhappy = True
        if utterance.sentiment is not None:
            self.rated = True
            self.unhappy = self.unhappy or utterance.sentiment.is_negative

    @property
    def is_new_complaint(self) -> bool:
        """Not a complaint the categories already cover, and not small
        talk: a wording the AI filed under a category on any call is
        known, and one it rated without ever finding the customer unhappy
        (a greeting, a registration number) is no complaint. A wording the
        AI never rated is kept: there is nothing to judge it by."""
        if self.categorised:
            return False
        return self.unhappy or not self.rated


class RuleBasedEmergingComplaintDiscoveryProvider(EmergingComplaintDiscoveryProvider):
    """Deterministic, LLM-free baseline for emerging-complaint discovery.

    Flags customer phrasing that recurs, verbatim after normalization,
    across two or more distinct calls and does not already correspond to
    a known complaint category. Purely lexical - two calls have to phrase
    the complaint the same way (modulo case/punctuation/whitespace) to be
    grouped together; no embeddings, clustering, or LLM involved. A later
    milestone can swap in a smarter provider behind the same interface
    without this one needing to change.

    What the AI already said about each line during the call (its
    category and its tone) keeps known complaints and small talk out:
    see _Phrase.is_new_complaint.
    """

    def discover(
        self, request: EmergingComplaintDiscoveryRequest
    ) -> tuple[EmergingComplaintCandidate, ...]:
        phrases: dict[str, _Phrase] = {}

        known = _NORMALIZED_CATEGORIES | {_normalize(name) for name in request.known_categories}
        for record in request.call_records:
            self._collect_phrases(record, phrases, known)

        total_calls = len(request.call_records)
        candidates = []
        for wording in sorted(phrases):
            phrase = phrases[wording]
            distinct_call_ids = sorted(set(phrase.call_ids))
            if len(distinct_call_ids) < MIN_RECURRING_CALLS or not phrase.is_new_complaint:
                continue

            confidence = min(1.0, len(distinct_call_ids) / total_calls)

            candidates.append(
                EmergingComplaintCandidate(
                    candidate_id=_stable_candidate_id(wording),
                    proposed_name=_proposed_name(wording),
                    description=_description(len(distinct_call_ids)),
                    evidence=tuple(phrase.quotes),
                    occurrence_count=len(phrase.call_ids),
                    confidence=confidence,
                    call_ids=tuple(distinct_call_ids),
                )
            )

        return tuple(candidates)

    def _collect_phrases(
        self,
        record: CallComplaintRecord,
        phrases: dict[str, _Phrase],
        known_categories: frozenset[str] = _NORMALIZED_CATEGORIES,
    ) -> None:
        for utterance in record.utterances:
            if utterance.speaker_role != SpeakerRole.CUSTOMER:
                continue

            normalized = _normalize(utterance.transcript)

            # An existing category, however phrased, is not "emerging".
            if normalized in known_categories:
                continue

            if len(normalized.split()) < MIN_PHRASE_WORDS:
                continue

            phrases.setdefault(normalized, _Phrase()).add(record.call_id, utterance)