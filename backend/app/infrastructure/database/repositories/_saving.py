"""How a repository stores one row."""

from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.database.base import Base


def save_row(session_factory: sessionmaker[Session], model: Base) -> None:
    """Insert the row, or update the one with the same primary key.

    Never delete-and-reinsert: deleting a row takes the rows that reference
    it with it (ON DELETE CASCADE), and resets anything the database filled
    in. For a model without relationships."""
    with session_factory() as session, session.begin():
        session.merge(model)
