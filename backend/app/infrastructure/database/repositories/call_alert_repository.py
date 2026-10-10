from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.call_alert import (
    CallAlert,
    CallAlertType,
    QuestionOutcome,
    QuestionOutcomeChoice,
)
from app.infrastructure.database.models import CallAlertModel, QuestionOutcomeModel
from app.infrastructure.database.repositories._saving import save_row
from app.services.call_alerts import CallAlertRepository, QuestionOutcomeRepository


class PostgresCallAlertRepository(CallAlertRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, alert: CallAlert) -> None:
        save_row(
            self._session_factory,
            CallAlertModel(
                call_id=alert.call_id,
                alert_type=alert.alert_type.value,
                subject=alert.subject,
                message=alert.message,
                raised_at=alert.raised_at,
                cleared_at=alert.cleared_at,
            ),
        )

    def list_for_calls(self, call_ids: Iterable[str]) -> dict[str, tuple[CallAlert, ...]]:
        ids = list(call_ids)
        if not ids:
            return {}
        with self._session_factory() as session:
            models = session.scalars(
                select(CallAlertModel)
                .where(CallAlertModel.call_id.in_(ids))
                .order_by(CallAlertModel.raised_at, CallAlertModel.alert_type)
            ).all()
        found: dict[str, list[CallAlert]] = {}
        for model in models:
            found.setdefault(model.call_id, []).append(
                CallAlert(
                    call_id=model.call_id,
                    alert_type=CallAlertType(model.alert_type),
                    subject=model.subject,
                    message=model.message,
                    raised_at=model.raised_at,
                    cleared_at=model.cleared_at,
                )
            )
        return {call_id: tuple(alerts) for call_id, alerts in found.items()}


class PostgresQuestionOutcomeRepository(QuestionOutcomeRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, outcome: QuestionOutcome) -> None:
        save_row(
            self._session_factory,
            QuestionOutcomeModel(
                call_id=outcome.call_id,
                question=outcome.question,
                target_category=outcome.target_category,
                outcome=outcome.outcome.value,
                user_id=outcome.user_id,
                created_at=outcome.created_at,
            ),
        )

    def list_for_calls(self, call_ids: Iterable[str]) -> dict[str, tuple[QuestionOutcome, ...]]:
        ids = list(call_ids)
        if not ids:
            return {}
        with self._session_factory() as session:
            models = session.scalars(
                select(QuestionOutcomeModel)
                .where(QuestionOutcomeModel.call_id.in_(ids))
                .order_by(QuestionOutcomeModel.created_at)
            ).all()
        found: dict[str, list[QuestionOutcome]] = {}
        for model in models:
            found.setdefault(model.call_id, []).append(
                QuestionOutcome(
                    call_id=model.call_id,
                    question=model.question,
                    target_category=model.target_category,
                    outcome=QuestionOutcomeChoice(model.outcome),
                    user_id=model.user_id,
                    created_at=model.created_at,
                )
            )
        return {call_id: tuple(outcomes) for call_id, outcomes in found.items()}

    def totals(self) -> tuple[int, int]:
        with self._session_factory() as session:
            counts = dict(
                session.execute(
                    select(QuestionOutcomeModel.outcome, func.count()).group_by(
                        QuestionOutcomeModel.outcome
                    )
                ).all()
            )
        return (
            counts.get(QuestionOutcomeChoice.ACCEPTED.value, 0),
            counts.get(QuestionOutcomeChoice.SKIPPED.value, 0),
        )
