"""
One-off PostgreSQL persistence smoke test.

Not part of the application or the pytest suite — run manually:
    python scripts/smoke_test_conversation.py

Reuses the EXISTING composition wiring (app.composition.database) and the
EXISTING ConversationRepository interface. No domain models, repository
interfaces, schema, migrations, or services are touched or modified.
"""

import sys
import uuid

from app.core.config import get_settings
from app.composition.database import build_production_repositories
from app.domain.conversation import Conversation
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.models import ConversationModel


def main() -> int:
    settings = get_settings()
    print(f"DATABASE_URL configured: {bool(settings.database_url and settings.database_url != 'not_configured')}")

    call_id = f"smoke-test-{uuid.uuid4()}"

    # --- Step 1: build repositories against the REAL configured Postgres,
    # via the existing production composition root. No SQLite, no in-memory. ---
    repos_write = build_production_repositories(settings)
    repo_under_test = repos_write.conversation
    print(f"Repository under test: {type(repo_under_test).__name__}")
    print("PostgreSQL table: conversations (+ utterances)")

    # --- Step 2: create a temporary domain record via the repository ---
    original = Conversation(call_id=call_id, start_time=0.0)
    original.add_utterance(
        Utterance(
            utterance_id=f"{call_id}-u1",
            transcript="smoke test utterance",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=1.0,
        )
    )

    # --- Step 3: save + commit (PostgresConversationRepository.save()
    # opens its own session and commits via `with session.begin():`,
    # then the session is closed on exiting the `with` block) ---
    repo_under_test.save(original)
    print(f"Saved conversation call_id={call_id}, commit + session close done.")

    # --- Step 4: brand-new session factory / repository instance, proving
    # this isn't just reading back from an ORM identity map or open session ---
    repos_read = build_production_repositories(settings)
    repo_new_session = repos_read.conversation
    assert repo_new_session is not repo_under_test

    reloaded = repo_new_session.get(call_id)

    # --- Step 5: verify ---
    survived = reloaded is not None
    matches = False
    if survived:
        matches = (
            reloaded.call_id == original.call_id
            and reloaded.status == original.status
            and reloaded.start_time == original.start_time
            and reloaded.utterance_count == original.utterance_count
            and reloaded.utterances[0].transcript == original.utterances[0].transcript
            and reloaded.utterances[0].speaker_role == original.utterances[0].speaker_role
        )

    print(f"Survived new session: {survived}")
    print(f"Data matches original: {matches}")

    # --- Step 6: cleanup. NOTE: ConversationRepository has no delete()
    # method in its interface (save/get only), and this script must not
    # add one. Falling back to a direct session delete using the existing
    # ConversationModel ORM class (not a new abstraction, just using what
    # infrastructure/database/models.py already exports) so no orphan
    # smoke-test row is left behind. ---
    cleanup_ok = False
    try:
        from app.infrastructure.database.engine import build_engine, build_session_factory

        engine = build_engine(settings)
        session_factory = build_session_factory(engine)
        with session_factory() as session, session.begin():
            row = session.get(ConversationModel, call_id)
            if row is not None:
                session.delete(row)  # cascades to utterances via relationship
        with session_factory() as verify_session:
            cleanup_ok = verify_session.get(ConversationModel, call_id) is None
    except Exception as exc:  # noqa: BLE001
        print(f"Cleanup raised an exception: {exc!r}")

    print(f"Cleanup succeeded: {cleanup_ok}")

    return 0 if (survived and matches and cleanup_ok) else 1


if __name__ == "__main__":
    sys.exit(main())