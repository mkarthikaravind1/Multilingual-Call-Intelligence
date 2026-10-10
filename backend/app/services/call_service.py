from app.domain.conversation import CallDirection, Conversation, ConversationStatus
from app.domain.utterance import Utterance
from app.services.conversation_service import ConversationCompletion, ConversationService


class CallService:
    def __init__(self, conversation_service: ConversationService) -> None:
        self._conversation_service = conversation_service

    def start_call(
        self,
        call_id: str,
        start_time: float = 0.0,
        direction: CallDirection | None = None,
        location_id: str | None = None,
        executive_user_id: str | None = None,
    ) -> Conversation:
        return self._conversation_service.create_conversation(
            call_id=call_id,
            start_time=start_time,
            direction=direction,
            location_id=location_id,
            executive_user_id=executive_user_id,
        )

    def assign_executive(
        self, call_id: str, executive_user_id: str, location_id: str | None = None
    ) -> Conversation:
        return self._conversation_service.assign_executive(
            call_id, executive_user_id, location_id
        )

    def get_call(self, call_id: str) -> Conversation:
        return self._conversation_service.get_conversation(call_id)

    def list_calls(self, limit: int, offset: int) -> tuple[Conversation, ...]:
        return self._conversation_service.list_conversations(limit, offset)

    def count_calls(self) -> int:
        return self._conversation_service.count_conversations()

    def count_calls_by_status(self) -> dict[ConversationStatus, int]:
        return self._conversation_service.count_conversations_by_status()

    def add_utterance(
        self,
        call_id: str,
        utterance: Utterance,
    ) -> Conversation:
        return self._conversation_service.add_utterance(
            call_id=call_id,
            utterance=utterance,
        )

    def update_latest_utterance(
        self,
        call_id: str,
        utterance: Utterance,
    ) -> Conversation:
        return self._conversation_service.update_latest_utterance(
            call_id=call_id,
            utterance=utterance,
        )

    def replace_transcript(
        self,
        call_id: str,
        utterances: tuple[Utterance, ...],
    ) -> Conversation:
        return self._conversation_service.replace_transcript(call_id, utterances)

    def end_call(
        self,
        call_id: str,
        end_time: float,
    ) -> ConversationCompletion:
        return self._conversation_service.complete_conversation(
            call_id=call_id,
            end_time=end_time,
        )