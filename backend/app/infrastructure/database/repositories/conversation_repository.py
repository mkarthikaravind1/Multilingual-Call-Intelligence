from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.domain.conversation import (
    Conversation,
    ConversationAlreadyExistsError,
    ConversationStatus,
)
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
    # Rebuild as ACTIVE so add_utterance() accepts the stored utterances,
    # then restore the persisted status (a completed call rejects new ones).
    conversation = Conversation(
        call_id=model.call_id,
        status=ConversationStatus.ACTIVE,
        start_time=model.start_time,
        end_time=model.end_time,
    )
    for utterance_model in model.utterances:
        conversation.add_utterance(_utterance_to_domain(utterance_model))
    conversation.status = ConversationStatus(model.status)
    return conversation


def _conversation_to_model(conversation: Conversation) -> ConversationModel:
    return ConversationModel(
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


class PostgresConversationRepository(ConversationRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, conversation: Conversation) -> None:
        try:
            with self._session_factory() as session, session.begin():
                if session.get(ConversationModel, conversation.call_id) is not None:
                    raise ConversationAlreadyExistsError(conversation.call_id)
                session.add(_conversation_to_model(conversation))
        except IntegrityError as exc:
            # Another process inserted the same call_id between our read and write.
            raise ConversationAlreadyExistsError(conversation.call_id) from exc

    def save(self, conversation: Conversation) -> None:
        with self._session_factory() as session, session.begin():
            existing = session.get(ConversationModel, conversation.call_id)
            # Persistence-only creation time; carried across the delete/re-insert.
            created_at = None if existing is None else existing.created_at
            if existing is not None:
                session.delete(existing)
                session.flush()

            model = _conversation_to_model(conversation)
            if created_at is not None:
                model.created_at = created_at
            session.add(model)

    def get(self, call_id: str) -> Conversation | None:
        with self._session_factory() as session:
            model = session.get(ConversationModel, call_id)
            return None if model is None else _conversation_to_domain(model)

    def list_page(self, limit: int, offset: int) -> tuple[Conversation, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(ConversationModel)
                .options(selectinload(ConversationModel.utterances))
                .order_by(
                    ConversationModel.created_at.desc(),
                    ConversationModel.call_id,
                )
                .limit(limit)
                .offset(offset)
            ).all()
            return tuple(_conversation_to_domain(model) for model in models)

    def count(self) -> int:
        with self._session_factory() as session:
            return session.scalar(select(func.count()).select_from(ConversationModel)) or 0

    def count_by_status(self) -> dict[ConversationStatus, int]:
        counts = {status: 0 for status in ConversationStatus}
        with self._session_factory() as session:
            rows = session.execute(
                select(ConversationModel.status, func.count()).group_by(
                    ConversationModel.status
                )
            ).all()
        for status, total in rows:
            counts[ConversationStatus(status)] = total
        return counts