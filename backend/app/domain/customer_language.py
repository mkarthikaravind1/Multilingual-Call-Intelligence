from collections import Counter
from collections.abc import Iterable

from app.core.languages import ENGLISH, INDIC_LANGUAGES
from app.domain.utterance import SpeakerRole, Utterance


def main_indic_language(utterances: Iterable[Utterance]) -> str | None:
    """The Indian language heard in most of these utterances, or None when
    the speech is English. A line mixing English into Tamil counts for
    Tamil, so English words do not outvote the Tamil. English-only lines
    count too, by their words: an English call with one line mislabelled
    Tamil stays English, while a Tamil speaker's short "okay, thank you"
    lines do not outweigh their Tamil."""
    words: Counter[str] = Counter()
    english_words = 0
    for utterance in utterances:
        length = len(utterance.transcript.split())
        indic = {language for language in utterance.languages if language in INDIC_LANGUAGES}
        if indic:
            for language in indic:
                words[language] += length
        elif ENGLISH in utterance.languages:
            english_words += length
    if not words:
        return None
    language, count = words.most_common(1)[0]
    return language if count > english_words else None


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
