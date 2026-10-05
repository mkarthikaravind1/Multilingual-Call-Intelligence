"""Explainable evidence, from what someone says, of whether they are the ICR
or the customer.

A positive score points to the ICR (greetings, offers of help, asking for
the customer's details), a negative one to the customer (their own vehicle,
calling about a problem). English patterns also catch English used in
code-mixed speech. The native-script entries cover the most common
phrasings in Tamil, Telugu, Kannada and Malayalam; they should be reviewed
by native speakers and are the place to extend coverage. Phrases from the
ICR's own script (e.g. "welcome to ABC Motors") can be added in the
ROLE_ICR_PHRASES setting.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class _Cue:
    weight: int
    english: re.Pattern[str] | None
    native: tuple[str, ...] = ()

    def matches(self, text: str) -> bool:
        if self.english is not None and self.english.search(text):
            return True
        return any(phrase in text for phrase in self.native)


def _words(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_CUES = (
    # The ICR answering the call.
    _Cue(
        3,
        _words(
            r"\b(thank(s| you) for (calling|contacting)|how (may|can|shall) i (help|assist)"
            r"|what can i do for you|welcome to)\b"
        ),
        (
            "எப்படி உதவ", "என்ன உதவி வேண்டும்",  # Tamil
            "ఎలా సహాయం", "ఏం సహాయం",  # Telugu
            "ಹೇಗೆ ಸಹಾಯ", "ಏನು ಸಹಾಯ",  # Kannada
            "എങ്ങനെ സഹായിക്കാ", "എന്ത് സഹായം",  # Malayalam
        ),
    ),
    # The ICR asking for the customer's details or taking action.
    _Cue(
        1,
        _words(
            r"\b((may|can|could) i (know|have|get) your|(please )?(share|tell me|confirm) your"
            r"|your (vehicle|registration|reg\.?|mobile|phone|job card|complaint|ticket) (number|no\.?)"
            r"|sorry for the (inconvenience|delay|trouble)|i will (check|arrange|escalate|raise|update|call you)"
            r"|we will (check|arrange|call you|update|send)|(complaint|ticket|job card) (id|number) is)\b"
        ),
        (
            "உங்கள் வண்டி எண்", "உங்க பேர்",  # Tamil
            "మీ వాహనం నంబర్", "మీ పేరు",  # Telugu
            "ನಿಮ್ಮ ವಾಹನ ಸಂಖ್ಯೆ", "ನಿಮ್ಮ ಹೆಸರು",  # Kannada
            "നിങ്ങളുടെ വണ്ടി നമ്പർ", "നിങ്ങളുടെ പേര്",  # Malayalam
        ),
    ),
    # The customer talking about their own vehicle.
    _Cue(
        -2,
        _words(r"\bmy (car|bike|vehicle|scooter|scooty|two[- ]wheeler|truck|auto)\b"),
        (
            "என் வண்டி", "என்னுடைய வண்டி", "என் கார்", "என்னோட வண்டி",  # Tamil
            "నా బండి", "నా కారు", "నా వాహనం",  # Telugu
            "ನನ್ನ ಗಾಡಿ", "ನನ್ನ ಕಾರ್", "ನನ್ನ ವಾಹನ",  # Kannada
            "എന്റെ വണ്ടി", "എന്റെ കാർ", "എന്റെ വാഹനം",  # Malayalam
        ),
    ),
    # The customer explaining why they called or chasing an update.
    _Cue(
        -2,
        _words(
            r"\b(i('m| am) calling (about|regarding|for|because)|i want to (complain|know|ask)"
            r"|i (gave|had given|have given|dropped|left) (my|the) |nobody (called|told)"
            r"|no one (called|told)|still not (done|ready|fixed|repaired)|when will (it|my|the vehicle) be)\b"
        ),
        (),
    ),
)


class ContentRoleScorer:
    def __init__(self, extra_icr_phrases: Iterable[str] = ()) -> None:
        phrases = tuple(p.strip().casefold() for p in extra_icr_phrases if p.strip())
        self._extra_icr_phrases = phrases

    def score(self, transcript: str) -> int:
        """> 0: sounds like the ICR, < 0: like the customer, 0: no evidence."""
        text = transcript.strip()
        if not text:
            return 0
        total = sum(cue.weight for cue in _CUES if cue.matches(text))
        folded = text.casefold()
        if any(phrase in folded for phrase in self._extra_icr_phrases):
            total += 3
        return total
