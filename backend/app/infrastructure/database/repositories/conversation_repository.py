from sqlalchemy.orm import Session, sessionmaker

from app.domain.conversation import Conversation, ConversationStatus
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.models import ConversationModel, UtteranceModel
from app.services.conversation_repository import ConversationRepository


def _utterance_to_domain(model: UtteranceModel) -> Utterance:
    return Utterance(
        utterance_id=model.utterance_id,
        transcript=model.transcript,
        speaker_role=SpeakerRole(model.speaker_role),
        languages=tuple(model.languages),
        start_time=model.start_time,
        end_time=model.end_time,
        confidence=model.confidence,
    )


def _conversation_to_domain(model: ConversationModel) -> Conversation:
    conversation = Conversation(
        call_id=model.call_id,
        status=ConversationStatus(model.status),
        start_time=model.start_time,
        end_time=model.end_time,
    )
    for utterance_model in model.utterances:
        conversation.add_utterance(_utterance_to_domain(utterance_model))
    return conversation


class PostgresConversationRepository(ConversationRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, conversation: Conversation) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(ConversationModel, conversation.call_id)
            if existing is not None:
                session.delete(existing)
                session.flush()

            model = ConversationModel(
                call_id=conversation.call_id,
                status=conversation.status.value,
                start_time=conversation.start_time,
                end_time=conversation.end_time,
                utterances=[
                    UtteranceModel(
                        utterance_id=utterance.utterance_id,
                        call_id=conversation.call_id,
                        transcript=utterance.transcript,
                        speaker_role=utterance.speaker_role.value,
                        languages=list(utterance.languages),
                        start_time=utterance.start_time,
                        end_time=utterance.end_time,
                        confidence=utterance.confidence,
                    )
                    for utterance in conversation.utterances
                ],
            )
            session.add(model)

    def get(self, call_id: str) -> Conversation | None:
        with self._session_factory() as session:
            model = session.get(ConversationModel, call_id)
            return None if model is None else _conversation_to_domain(model)