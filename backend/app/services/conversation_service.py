from app.domain.conversation import Conversation
from app.domain.utterance import Utterance
from app.services.conversation_repository import ConversationRepository

class ConversationNotFoundError(Exception):
    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        super().__init__(f"No conversation found with id: {call_id!r}")


class ConversationService:
    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    def create_conversation(self, call_id: str, start_time: float = 0.0) -> Conversation:
        conversation = Conversation(call_id=call_id, start_time=start_time)
        self._repository.save(conversation)
        return conversation

    def get_conversation(self, call_id: str) -> Conversation:
        conversation = self._repository.get(call_id)
        if conversation is None:
            raise ConversationNotFoundError(call_id)
        return conversation

    def add_utterance(self, call_id: str, utterance: Utterance) -> Conversation:
        conversation = self.get_conversation(call_id)
        conversation.add_utterance(utterance)
        self._repository.save(conversation)
        return conversation

    def complete_conversation(self, call_id: str, end_time: float) -> Conversation:
        conversation = self.get_conversation(call_id)
        conversation.complete(end_time)
        self._repository.save(conversation)
        return conversation