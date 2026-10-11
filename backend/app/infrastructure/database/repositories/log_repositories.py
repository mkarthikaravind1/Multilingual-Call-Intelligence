from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.orm import Session, defer, sessionmaker

from app.infrastructure.database.models import AiLogModel, AuditLogModel
from app.services.ai_log import (
    AiLogEntry,
    AiLogFilter,
    AiLogRepository,
    AiLogTotals,
    AiOutcome,
)
from app.services.audit_log import AuditEntry, AuditFilter, AuditLogRepository


def _audit_entry(model: AuditLogModel) -> AuditEntry:
    return AuditEntry(
        occurred_at=model.occurred_at,
        action=model.action,
        method=model.method,
        path=model.path,
        status_code=model.status_code,
        user_id=model.user_id,
        role=model.role,
        target_type=model.target_type,
        target_id=model.target_id,
        ip_address=model.ip_address,
        request_id=model.request_id,
        detail=model.detail,
        entry_id=model.id,
    )


def _audit_where(query: Select, filters: AuditFilter) -> Select:
    model = AuditLogModel
    if filters.user_id is not None:
        query = query.where(model.user_id == filters.user_id)
    if filters.action is not None:
        query = query.where(model.action == filters.action)
    if filters.succeeded is not None:
        query = query.where(
            model.status_code < 400 if filters.succeeded else model.status_code >= 400
        )
    if filters.target_id is not None:
        query = query.where(model.target_id == filters.target_id)
    if filters.occurred_from is not None:
        query = query.where(model.occurred_at >= filters.occurred_from)
    if filters.occurred_to is not None:
        query = query.where(model.occurred_at < filters.occurred_to)
    return query


class PostgresAuditLogRepository(AuditLogRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add_many(self, entries: list[AuditEntry]) -> None:
        with self._session_factory() as session, session.begin():
            session.add_all(
                AuditLogModel(
                    occurred_at=entry.occurred_at,
                    user_id=entry.user_id,
                    role=entry.role,
                    action=entry.action,
                    method=entry.method,
                    path=entry.path,
                    target_type=entry.target_type,
                    target_id=entry.target_id,
                    status_code=entry.status_code,
                    ip_address=entry.ip_address,
                    request_id=entry.request_id,
                    detail=entry.detail,
                )
                for entry in entries
            )

    def search(
        self, filters: AuditFilter, limit: int, offset: int
    ) -> tuple[tuple[AuditEntry, ...], int]:
        with self._session_factory() as session:
            total = session.scalar(
                _audit_where(select(func.count()).select_from(AuditLogModel), filters)
            )
            models = session.scalars(
                _audit_where(select(AuditLogModel), filters)
                .order_by(AuditLogModel.occurred_at.desc(), AuditLogModel.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return tuple(_audit_entry(model) for model in models), int(total or 0)

    def actions(self) -> tuple[str, ...]:
        with self._session_factory() as session:
            return tuple(
                session.scalars(
                    select(AuditLogModel.action).distinct().order_by(AuditLogModel.action)
                ).all()
            )

    def delete_before(self, cutoff: float) -> int:
        with self._session_factory() as session, session.begin():
            result = session.execute(
                delete(AuditLogModel).where(AuditLogModel.occurred_at < cutoff)
            )
            return int(result.rowcount or 0)


def _ai_entry(model: AiLogModel, with_text: bool) -> AiLogEntry:
    return AiLogEntry(
        entry_id=model.id,
        call_id=model.call_id,
        task=model.task,
        model=model.model,
        started_at=model.started_at,
        duration_ms=model.duration_ms,
        outcome=AiOutcome(model.outcome),
        attempt=model.attempt,
        prompt=model.prompt if with_text else None,
        answer=model.answer if with_text else None,
        prompt_chars=model.prompt_chars,
        answer_chars=model.answer_chars,
        prompt_tokens=model.prompt_tokens,
        completion_tokens=model.completion_tokens,
        note=model.note,
    )


def _ai_where(query: Select, filters: AiLogFilter) -> Select:
    model = AiLogModel
    if filters.call_id is not None:
        query = query.where(model.call_id == filters.call_id)
    if filters.task is not None:
        query = query.where(model.task == filters.task)
    if filters.outcome is not None:
        query = query.where(model.outcome == filters.outcome.value)
    if filters.started_from is not None:
        query = query.where(model.started_at >= filters.started_from)
    if filters.started_to is not None:
        query = query.where(model.started_at < filters.started_to)
    return query


class PostgresAiLogRepository(AiLogRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add_many(self, entries: list[AiLogEntry]) -> None:
        with self._session_factory() as session, session.begin():
            session.add_all(
                AiLogModel(
                    id=entry.entry_id,
                    call_id=entry.call_id,
                    task=entry.task,
                    model=entry.model,
                    started_at=entry.started_at,
                    duration_ms=entry.duration_ms,
                    outcome=entry.outcome.value,
                    attempt=entry.attempt,
                    prompt=entry.prompt,
                    answer=entry.answer,
                    prompt_chars=entry.prompt_chars,
                    answer_chars=entry.answer_chars,
                    prompt_tokens=entry.prompt_tokens,
                    completion_tokens=entry.completion_tokens,
                    note=entry.note,
                )
                for entry in entries
            )

    def set_outcome(self, entry_id: str, outcome: AiOutcome, note: str | None) -> None:
        with self._session_factory() as session, session.begin():
            session.execute(
                update(AiLogModel)
                .where(AiLogModel.id == entry_id)
                .values(outcome=outcome.value, note=note)
            )

    def get(self, entry_id: str) -> AiLogEntry | None:
        with self._session_factory() as session:
            model = session.get(AiLogModel, entry_id)
            return None if model is None else _ai_entry(model, with_text=True)

    def search(
        self, filters: AiLogFilter, limit: int, offset: int
    ) -> tuple[tuple[AiLogEntry, ...], int]:
        with self._session_factory() as session:
            total = session.scalar(
                _ai_where(select(func.count()).select_from(AiLogModel), filters)
            )
            # A page of prompts would be megabytes nobody reads in a list.
            models = session.scalars(
                _ai_where(select(AiLogModel), filters)
                .options(defer(AiLogModel.prompt), defer(AiLogModel.answer))
                .order_by(AiLogModel.started_at.desc(), AiLogModel.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return tuple(_ai_entry(model, with_text=False) for model in models), int(total or 0)

    def totals(self, filters: AiLogFilter) -> AiLogTotals:
        model = AiLogModel
        with self._session_factory() as session:
            requests, prompt_tokens, completion_tokens, counted = session.execute(
                _ai_where(
                    select(
                        func.count(),
                        func.coalesce(func.sum(model.prompt_tokens), 0),
                        func.coalesce(func.sum(model.completion_tokens), 0),
                        func.count(model.prompt_tokens),
                    ).select_from(model),
                    filters,
                )
            ).one()
            return AiLogTotals(
                requests=int(requests),
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                uncounted=int(requests) - int(counted),
            )

    def tasks(self) -> tuple[str, ...]:
        with self._session_factory() as session:
            return tuple(
                session.scalars(
                    select(AiLogModel.task).distinct().order_by(AiLogModel.task)
                ).all()
            )

    def delete_before(self, cutoff: float) -> int:
        with self._session_factory() as session, session.begin():
            result = session.execute(delete(AiLogModel).where(AiLogModel.started_at < cutoff))
            return int(result.rowcount or 0)
