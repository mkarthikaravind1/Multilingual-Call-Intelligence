from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.domain.call_number import CallNumbers

# Created by migration 0027.
CALL_NUMBER_SEQUENCE = "call_number_seq"


class PostgresCallNumbers(CallNumbers):
    """The next value of a database sequence: unique across instances, and
    never handed out again even when the call that took it failed to save."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def next(self) -> int:
        with self._session_factory() as session:
            return int(session.execute(text(f"SELECT nextval('{CALL_NUMBER_SEQUENCE}')")).scalar_one())
