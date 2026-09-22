from app.domain.conversation import Conversation

# Fallback when no utterance carries a language (e.g. an empty conversation).
DEFAULT_LANGUAGE = "en"


def extract_languages(conversation: Conversation) -> tuple[str, ...]:
    """Collects the distinct utterance languages, in first-seen order,
    falling back to DEFAULT_LANGUAGE when the conversation carries none.
    """
    languages: list[str] = []
    for utterance in conversation.utterances:
        for lang in utterance.languages:
            if lang not in languages:
                languages.append(lang)
    if not languages:
        languages.append(DEFAULT_LANGUAGE)
    return tuple(languages)