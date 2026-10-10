"""A conversation as LLM prompts show it."""

from app.domain.conversation import Conversation


def numbered_transcript(conversation: Conversation) -> str:
    """Every line with its number (1 is the call's first line), so an
    answer can name lines without repeating them."""
    return "\n".join(
        f"[{number}] {u.speaker_role.value}: {u.transcript.strip()}"
        for number, u in enumerate(conversation.utterances, start=1)
    )
