import threading
from dataclasses import dataclass

from app.domain.conversation import Conversation, ConversationStatus
from app.domain.utterance import Utterance
from app.services.conversation_repository import ConversationRepository

class ConversationNotFoundError(Exception):
    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        super().__init__(f"No conversation found with id: {call_id!r}")


@dataclass(frozen=True)
class ConversationCompletion:
    conversation: Conversation
    completed_now: bool


class ConversationService:
    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def _lock_for(self, call_id: str) -> threading.Lock:
        # Guards the read -> mutate -> save sequence in add_utterance() and
        # complete_conversation() so two near-simultaneous writes for the
        # same call (e.g. streamed audio and the status webhook landing
        # close together) can't silently overwrite one another.
        with self._locks_guard:
            lock = self._locks.get(call_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[call_id] = lock
            return lock

    def create_conversation(self, call_id: str, start_time: float = 0.0) -> Conversation:
        conversation = Conversation(call_id=call_id, start_time=start_time)
        self._repository.save(conversation)
        return conversation

    def get_conversation(self, call_id: str) -> Conversation:
        conversation = self._repository.get(call_id)
        if conversation is None:
            raise ConversationNotFoundError(call_id)
        return conversation

    def list_conversations(self, limit: int, offset: int) -> tuple[Conversation, ...]:
        return self._repository.list_page(limit, offset)

    def count_conversations(self) -> int:
        return self._repository.count()

    def count_conversations_by_status(self) -> dict[ConversationStatus, int]:
        return self._repository.count_by_status()

    def add_utterance(self, call_id: str, utterance: Utterance) -> Conversation:
        with self._lock_for(call_id):
            conversation = self.get_conversation(call_id)
            conversation.add_utterance(utterance)
            self._repository.save(conversation)
            return conversation

    def complete_conversation(self, call_id: str, end_time: float) -> ConversationCompletion:
        # ACTIVE -> COMPLETED happens once; repeats return the call unchanged,
        # keeping the original end_time.
        with self._lock_for(call_id):
            conversation = self.get_conversation(call_id)
            if conversation.status == ConversationStatus.COMPLETED:
                return ConversationCompletion(conversation, completed_now=False)
            conversation.complete(end_time)
            self._repository.save(conversation)
            return ConversationCompletion(conversation, completed_now=True)