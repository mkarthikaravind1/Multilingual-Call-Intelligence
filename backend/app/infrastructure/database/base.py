from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """Shared declarative base for all persistence/ORM models.

    Domain dataclasses in app.domain / app.services never import this.
    """