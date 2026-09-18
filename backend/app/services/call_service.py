from app.domain.conversation import Conversation
from app.domain.utterance import Utterance
from app.services.conversation_service import ConversationService


class CallService:
    def __init__(self, conversation_service: ConversationService) -> None:
        self._conversation_service = conversation_service

    def start_call(
        self,
        call_id: str,
        start_time: float = 0.0,
    ) -> Conversation:
        return self._conversation_service.create_conversation(
            call_id=call_id,
            start_time=start_time,
        )

    def get_call(self, call_id: str) -> Conversation:
        return self._conversation_service.get_conversation(call_id)

    def add_utterance(
        self,
        call_id: str,
        utterance: Utterance,
    ) -> Conversation:
        return self._conversation_service.add_utterance(
            call_id=call_id,
            utterance=utterance,
        )

    def end_call(
        self,
        call_id: str,
        end_time: float,
    ) -> Conversation:
        return self._conversation_service.complete_conversation(
            call_id=call_id,
            end_time=end_time,
        )