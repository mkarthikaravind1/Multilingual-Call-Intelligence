from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.domain.sentiment import SentimentLabel
from app.domain.conversation import (
    CallDirection,
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
        sentiment=None if model.sentiment is None else SentimentLabel(model.sentiment),
        sentiment_confidence=model.sentiment_confidence,
        complaint_categories=tuple(model.complaint_categories or ()),
    )


def _conversation_to_domain(model: ConversationModel) -> Conversation:
    # Rebuild as ACTIVE so add_utterance() accepts the stored utterances,
    # then restore the persisted status (a completed call rejects new ones).
    conversation = Conversation(
        call_id=model.call_id,
        status=ConversationStatus.ACTIVE,
        start_time=model.start_time,
        end_time=model.end_time,
        direction=None if model.direction is None else CallDirection(model.direction),
        location_id=model.location_id,
        executive_user_id=model.executive_user_id,
    )
    for utterance_model in model.utterances:
        conversation.add_utterance(_utterance_to_domain(utterance_model))
    conversation.status = ConversationStatus(model.status)
    return conversation


def _write_utterance(model: UtteranceModel, utterance: Utterance) -> UtteranceModel:
    model.transcript = utterance.transcript
    model.speaker_role = utterance.speaker_role.value
    model.languages = list(utterance.languages)
    model.start_time = utterance.start_time
    model.end_time = utterance.end_time
    model.confidence = utterance.confidence
    model.sentiment = None if utterance.sentiment is None else utterance.sentiment.value
    model.sentiment_confidence = utterance.sentiment_confidence
    # NULL rather than an empty list: most lines raise nothing.
    model.complaint_categories = list(utterance.complaint_categories) or None
    return model


def _utterance_to_model(call_id: str, utterance: Utterance) -> UtteranceModel:
    return _write_utterance(
        UtteranceModel(utterance_id=utterance.utterance_id, call_id=call_id), utterance
    )


def _write_call_fields(model: ConversationModel, conversation: Conversation) -> None:
    model.status = conversation.status.value
    model.start_time = conversation.start_time
    model.end_time = conversation.end_time
    model.direction = None if conversation.direction is None else conversation.direction.value
    model.location_id = conversation.location_id
    model.executive_user_id = conversation.executive_user_id


def _conversation_to_model(conversation: Conversation) -> ConversationModel:
    model = ConversationModel(
        call_id=conversation.call_id,
        utterances=[
            _utterance_to_model(conversation.call_id, utterance)
            for utterance in conversation.utterances
        ],
    )
    _write_call_fields(model, conversation)
    return model


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
            if existing is None:
                session.add(_conversation_to_model(conversation))
                return

            # Updated in place. A live call is saved on every utterance:
            # only what changed is written (deleting and re-inserting the
            # call rewrote its whole transcript each time), and the row
            # keeps its created_at.
            _write_call_fields(existing, conversation)
            stored = {model.utterance_id: model for model in existing.utterances}
            # Utterances no longer in the call (a revised transcript) are
            # deleted with this assignment.
            existing.utterances = [
                _write_utterance(stored[utterance.utterance_id], utterance)
                if utterance.utterance_id in stored
                else _utterance_to_model(conversation.call_id, utterance)
                for utterance in conversation.utterances
            ]

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