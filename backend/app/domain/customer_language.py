from collections import Counter
from collections.abc import Iterable

from app.core.languages import ENGLISH, INDIC_LANGUAGES
from app.domain.utterance import SpeakerRole, Utterance


def main_indic_language(utterances: Iterable[Utterance]) -> str | None:
    """The Indian language heard in most of these utterances, or None when
    they hold none (English only). English is left out of the count: Tamil
    speakers mix in English words, which must not outvote the Tamil."""
    counts: Counter[str] = Counter()
    for utterance in utterances:
        for language in set(utterance.languages):
            if language in INDIC_LANGUAGES:
                counts[language] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def customer_language(utterances: tuple[Utterance, ...]) -> str:
    """The language to address the customer in: the main Indian language of
    what the customer said, else English. While the customer's speech is not
    yet told apart, speech from an unknown speaker counts, then any speech."""
    for roles in (
        {SpeakerRole.CUSTOMER},
        {SpeakerRole.CUSTOMER, SpeakerRole.UNKNOWN},
    ):
        spoken = [u for u in utterances if u.speaker_role in roles]
        if spoken:
            return main_indic_language(spoken) or ENGLISH
    return main_indic_language(utterances) or ENGLISH
