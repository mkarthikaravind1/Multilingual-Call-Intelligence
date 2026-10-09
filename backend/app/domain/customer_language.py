from collections import Counter
from collections.abc import Iterable

from app.core.languages import ENGLISH, INDIC_LANGUAGES
from app.domain.utterance import SpeakerRole, Utterance


def main_indic_language(utterances: Iterable[Utterance]) -> str | None:
    """The Indian language heard in most of these utterances, or None when
    the speech is English. A line mixing English into Tamil counts for
    Tamil, so English words do not outvote the Tamil; but English-only
    lines that outnumber the Tamil ones make it English, so that one line
    mislabelled Tamil does not turn an English call into a Tamil one."""
    counts: Counter[str] = Counter()
    english_only = 0
    for utterance in utterances:
        indic = {language for language in utterance.languages if language in INDIC_LANGUAGES}
        if indic:
            counts.update(indic)
        elif ENGLISH in utterance.languages:
            english_only += 1
    if not counts:
        return None
    language, lines = counts.most_common(1)[0]
    return language if lines >= english_only else None


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
