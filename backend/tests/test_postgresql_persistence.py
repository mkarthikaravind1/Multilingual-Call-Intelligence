"""Feature-level tests for PostgreSQL persistence.

Runs against an in-memory SQLite database so the suite stays runnable
without a real PostgreSQL server. The repositories under test use plain
SQLAlchemy Core/ORM with no PostgreSQL-only constructs, so the same code
path is exercised against a real PostgreSQL server in production.
"""

import dataclasses

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.domain.active_improvement import ActiveImprovement, ActiveImprovementStatus
from app.domain.complaint_lifecycle import ComplaintLifecycleRecord, ComplaintLifecycleStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.improvement_candidate import (
    ImprovementCandidate,
    ImprovementReviewStatus,
    ImprovementSpecification,
    ImprovementType,
)
from app.domain.improvement_usage import ImprovementUsage
from app.domain.learning_evidence import EvidenceType, LearningComponent, LearningEvidence
from app.domain.learning_feedback import FeedbackType, LearningFeedback
from app.domain.learning_observation import LearningObservation
from app.domain.utterance import SpeakerRole, Utterance
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_session_factory
from app.infrastructure.database.models import (
    ComplaintCoverageModel,
    ConversationCoverageModel,
    ConversationModel,
    UtteranceModel,
)
from app.infrastructure.database.repositories.active_improvement_repository import (
    PostgresActiveImprovementRepository,
)
from app.infrastructure.database.repositories.complaint_customer_history_repository import (
    PostgresComplaintCustomerHistoryRepository,
)
from app.infrastructure.database.repositories.complaint_lifecycle_repository import (
    PostgresComplaintLifecycleRepository,
)
from app.infrastructure.database.repositories.conversation_coverage_repository import (
    PostgresConversationCoverageRepository,
)
from app.infrastructure.database.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from app.infrastructure.database.repositories.improvement_candidate_repository import (
    PostgresImprovementCandidateRepository,
)
from app.infrastructure.database.repositories.improvement_usage_repository import (
    PostgresImprovementUsageRepository,
)
from app.infrastructure.database.repositories.learning_evidence_repository import (
    PostgresLearningEvidenceRepository,
)
from app.infrastructure.database.repositories.learning_feedback_repository import (
    PostgresLearningFeedbackRepository,
)
from app.infrastructure.database.repositories.learning_observation_repository import (
    PostgresLearningObservationRepository,
)


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return build_session_factory(engine)


# 1. Database initialization -------------------------------------------------


def test_schema_creates_all_expected_tables(engine):
    tables = set(inspect(engine).get_table_names())
    assert tables == {
        "conversations",
        "utterances",
        "conversation_coverages",
        "complaint_coverages",
        "learning_evidence",
        "learning_observations",
        "learning_feedback",
        "improvement_candidates",
        "active_improvements",
        "improvement_usages",
        "complaint_lifecycle_records",
        "users",
    }


# 2 & 5. Save/get + relationships (conversation -> utterances) --------------


def test_conversation_round_trips_with_ordered_utterances(session_factory):
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-1", start_time=0.0)
    conversation.add_utterance(
        Utterance(
            utterance_id="u1",
            transcript="hello",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=1.0,
        )
    )
    conversation.add_utterance(
        Utterance(
            utterance_id="u2",
            transcript="hi there",
            speaker_role=SpeakerRole.ICR,
            languages=("en", "ta"),
            start_time=1.0,
            end_time=2.0,
            confidence=0.9,
        )
    )

    repo.save(conversation)
    loaded = repo.get("call-1")

    assert loaded is not None
    assert [u.utterance_id for u in loaded.utterances] == ["u1", "u2"]
    assert loaded.utterances[1].languages == ("en", "ta")
    assert loaded.utterances[1].confidence == 0.9
    assert repo.get("missing") is None


# 4. Update/upsert behaviour --------------------------------------------------


def test_conversation_save_replaces_previous_utterances(session_factory):
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-2", start_time=0.0)
    conversation.add_utterance(
        Utterance(
            utterance_id="u1",
            transcript="first version",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=1.0,
        )
    )
    repo.save(conversation)

    conversation.complete(end_time=5.0)
    repo.save(conversation)

    loaded = repo.get("call-2")
    assert loaded is not None
    assert loaded.utterance_count == 1
    assert loaded.end_time == 5.0
    assert loaded.status.value == "completed"



# 3, 5 & 8. List behaviour, coverage relationship, unique constraint --------


def test_conversation_coverage_persists_complaint_rows_and_enforces_uniqueness(
    session_factory,
):
    repo = PostgresConversationCoverageRepository(session_factory)
    coverage = ConversationCoverage(call_id="call-3")
    coverage.get_or_add("Cost").detect()
    coverage.get_or_add("Service Quality")
    repo.save(coverage)

    loaded = repo.get("call-3")
    assert loaded is not None
    assert {c.category for c in loaded.complaints} == {
        "Cost",
        "Service Quality",
    }

    Cost = loaded.get("Cost")
    assert Cost is not None
    assert Cost.status.value == "detected"


    with session_factory() as session, session.begin():
        session.add(ConversationCoverageModel(call_id="call-3b"))
        session.add(
            ComplaintCoverageModel(call_id="call-3b", category="Cost", status="detected")
        )
    with pytest.raises(IntegrityError):
        with session_factory() as session, session.begin():
            session.add(
                ComplaintCoverageModel(call_id="call-3b", category="Cost", status="probed")
            )


# 8. Cascade delete (ownership relationship) ---------------------------------


def test_deleting_conversation_cascades_to_utterances(session_factory):
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-4", start_time=0.0)
    conversation.add_utterance(
        Utterance(
            utterance_id="u1",
            transcript="hello",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=1.0,
        )
    )
    repo.save(conversation)

    with session_factory() as session, session.begin():
        session.delete(session.get(ConversationModel, "call-4"))

    with session_factory() as session:
        remaining = session.scalars(
            select(UtteranceModel).where(UtteranceModel.call_id == "call-4")
        ).all()
    assert remaining == []


# 6 & 9. Enum mapping + domain<->ORM mapping ---------------------------------


def test_learning_evidence_enum_and_optional_fields_round_trip(session_factory):
    repo = PostgresLearningEvidenceRepository(session_factory)
    evidence = LearningEvidence(
        evidence_id="ev-1",
        call_id="call-5",
        evidence_type=EvidenceType.HUMAN_CORRECTION,
        component=LearningComponent.COMPLAINT_DETECTION,
        description="Agent corrected the detected category",
        expected_value="Cost",
        actual_value="Service Quality",
        human_correction="Cost",
        created_at=100.0,
    )
    repo.save(evidence)

    loaded = repo.get("ev-1")
    assert loaded is not None
    assert loaded.evidence_type is EvidenceType.HUMAN_CORRECTION
    assert loaded.component is LearningComponent.COMPLAINT_DETECTION
    assert loaded.human_correction == "Cost"


    all_evidence = repo.list_all()
    assert len(all_evidence) == 1


def test_improvement_candidate_specification_is_nullable_and_maps_correctly(session_factory):
    repo = PostgresImprovementCandidateRepository(session_factory)

    without_spec = ImprovementCandidate(
        candidate_id="cand-1",
        improvement_type=ImprovementType.QUESTION_STRATEGY,
        title="Ask about Cost earlier",
        description="Observed pattern across calls",
        evidence=("ev-1",),
        occurrence_count=3,
        confidence=0.8,
        status=ImprovementReviewStatus.PENDING_REVIEW,
        created_at=10.0,
    )
    repo.save(without_spec)
    assert repo.get("cand-1").specification is None # type: ignore

    with_spec = ImprovementCandidate(
        candidate_id="cand-2",
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="Tighten Cost detection",
        description="Reduce false negatives",
        evidence=("ev-1", "ev-2"),
        occurrence_count=5,
        confidence=0.9,
        status=ImprovementReviewStatus.APPROVED,
        created_at=10.0,
        reviewed_at=20.0,
        specification=ImprovementSpecification(
            component=LearningComponent.COMPLAINT_DETECTION,
            current_behavior="Only flags explicit mentions",
            proposed_behavior="Also flags implicit Cost complaints",
            reason="Evidence shows repeated misses",
        ),
    )
    repo.save(with_spec)
    loaded = repo.get("cand-2")
    assert loaded is not None
    assert loaded.specification is not None
    assert (
        loaded.specification.proposed_behavior
        == "Also flags implicit Cost complaints"
    )

    assert {c.candidate_id for c in repo.list_all()} == {"cand-1", "cand-2"}


# 7. Persistence beyond a single session -------------------------------------


def test_data_survives_session_recreation(session_factory):
    repo = PostgresLearningObservationRepository(session_factory)
    repo.save(
        LearningObservation(
            observation_id="obs-1",
            call_id="call-6",
            component=LearningComponent.SENTIMENT_ANALYSIS,
            description="Predicted negative sentiment",
            predicted_value="negative",
            confidence=0.7,
            created_at=1.0,
        )
    )

    # A brand new repository instance sharing only the session factory (not
    # any in-memory state) must still see the row committed above.
    fresh_repo = PostgresLearningObservationRepository(session_factory)
    loaded = fresh_repo.get("obs-1")
    assert loaded is not None
    assert loaded.predicted_value == "negative"


# 10. Realistic end-to-end flow ----------------------------------------------


def test_end_to_end_call_and_learning_flow(session_factory):
    conversations = PostgresConversationRepository(session_factory)
    coverage_repo = PostgresConversationCoverageRepository(session_factory)
    evidence_repo = PostgresLearningEvidenceRepository(session_factory)
    observation_repo = PostgresLearningObservationRepository(session_factory)
    feedback_repo = PostgresLearningFeedbackRepository(session_factory)
    candidate_repo = PostgresImprovementCandidateRepository(session_factory)
    active_repo = PostgresActiveImprovementRepository(session_factory)
    usage_repo = PostgresImprovementUsageRepository(session_factory)
    lifecycle_repo = PostgresComplaintLifecycleRepository(session_factory)
    history_repo = PostgresComplaintCustomerHistoryRepository(session_factory)

    call_id = "call-e2e"

    conversation = Conversation(call_id=call_id, start_time=0.0)
    conversation.add_utterance(
        Utterance(
            utterance_id="u1",
            transcript="My bill is wrong",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=2.0,
        )
    )
    conversations.save(conversation)

    coverage = ConversationCoverage(call_id=call_id)
    coverage.get_or_add("Cost").detect()
    coverage_repo.save(coverage)

    observation_repo.save(
        LearningObservation(
            observation_id="obs-e2e",
            call_id=call_id,
            component=LearningComponent.COMPLAINT_DETECTION,
            description="Detected Cost complaint",
            predicted_value="Cost",
            confidence=0.6,
            created_at=1.0,
        )
    )
    feedback_repo.save(
        LearningFeedback(
            feedback_id="fb-e2e",
            observation_id="obs-e2e",
            feedback_type=FeedbackType.HUMAN_CORRECTION,
            corrected_value="Cost",
            outcome=None,
            created_at=2.0,
            call_id=call_id,
        )
    )
    evidence_repo.save(
        LearningEvidence(
            evidence_id="ev-e2e",
            call_id=call_id,
            evidence_type=EvidenceType.HUMAN_CORRECTION,
            component=LearningComponent.COMPLAINT_DETECTION,
            description="Confirmed Cost complaint",
            expected_value="Cost",
            actual_value="Cost",
            human_correction=None,
            created_at=2.0,
        )
    )

    spec = ImprovementSpecification(
        component=LearningComponent.COMPLAINT_DETECTION,
        current_behavior="Misses soft Cost language",
        proposed_behavior="Recognize soft Cost language",
        reason="Repeated evidence from live calls",
    )
    candidate = ImprovementCandidate(
        candidate_id="cand-e2e",
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="Recognize soft Cost language",
        description="From evidence ev-e2e",
        evidence=("ev-e2e",),
        occurrence_count=1,
        confidence=0.6,
        status=ImprovementReviewStatus.PENDING_REVIEW,
        created_at=3.0,
    )
    candidate_repo.save(candidate)
    approved = dataclasses.replace(
        candidate, status=ImprovementReviewStatus.APPROVED, reviewed_at=4.0
    )
    candidate_repo.save(approved)

    active = ActiveImprovement(
        improvement_id="active-e2e",
        candidate_id="cand-e2e",
        component=LearningComponent.COMPLAINT_DETECTION,
        specification=spec,
        status=ActiveImprovementStatus.ACTIVE,
        activated_at=5.0,
    )
    active_repo.save(active)
    usage_repo.save(
        ImprovementUsage(
            usage_id="usage-e2e",
            improvement_id="active-e2e",
            candidate_id="cand-e2e",
            call_id=call_id,
            component=LearningComponent.COMPLAINT_DETECTION,
            output_value="Cost",
            used_at=6.0,
        )
    )

    lifecycle_repo.save(
        ComplaintLifecycleRecord(
            complaint_id="complaint-e2e",
            call_id=call_id,
            category="Cost",
            status=ComplaintLifecycleStatus.DETECTED,
            first_detected_at=1.0,
            last_updated_at=1.0,
            customer_id="cust-1",
        )
    )

    # Assertions across the whole flow.
    loaded_conversation = conversations.get(call_id)
    assert loaded_conversation is not None
    assert loaded_conversation.utterance_count == 1

    loaded_coverage = coverage_repo.get(call_id)

    assert loaded_coverage is not None

    Cost = loaded_coverage.get("Cost")

    assert Cost is not None
    assert Cost.status.value == "detected"

    assert feedback_repo.get_by_observation_id("obs-e2e")[0].corrected_value == "Cost"
    approved_candidate = candidate_repo.get("cand-e2e")

    assert approved_candidate is not None
    assert approved_candidate.status is ImprovementReviewStatus.APPROVED

    active_improvement = active_repo.get_by_candidate_id("cand-e2e")
    assert active_improvement is not None
    assert active_improvement.improvement_id == "active-e2e"

    assert usage_repo.list_for_call(call_id)[0].output_value == "Cost"
    assert history_repo.get_active_for_customer("cust-1")[0].complaint_id == "complaint-e2e"
    assert history_repo.get_history_for_customer("cust-1")[0].category == "Cost"