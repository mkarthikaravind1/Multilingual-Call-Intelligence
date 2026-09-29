"""Feature-level tests for PostgreSQL persistence.

Runs against an in-memory SQLite database so the suite stays runnable
without a real PostgreSQL server. The repositories under test use plain
SQLAlchemy Core/ORM with no PostgreSQL-only constructs, so the same code
path is exercised against a real PostgreSQL server in production.
"""

import dataclasses
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.domain.active_improvement import ActiveImprovement, ActiveImprovementStatus
from app.domain.complaint_lifecycle import ComplaintLifecycleRecord, ComplaintLifecycleStatus
from app.ai.sentiment.provider import SentimentLabel, SentimentResult
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import (
    Conversation,
    ConversationAlreadyExistsError,
    ConversationStatus,
)
from app.domain.customer_contact import MessagingChannel
from app.domain.customer_summary_delivery import CustomerSummaryDelivery, DeliveryStatus
from app.domain.post_call_summary import ComplaintSummary, PostCallSummary
from app.domain.service_estimate import EstimatedPart, LabourEstimate, ServiceEstimate
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
from app.infrastructure.database.repositories.call_customer_repository import (
    PostgresCallCustomerRepository,
)
from app.domain.call_customer import CallCustomerLink
from app.domain.escalation import (
    Escalation,
    EscalationLevel,
    EscalationSignal,
    EscalationSignalType,
    EscalationStatus,
)
from app.infrastructure.database.repositories.escalation_repository import (
    PostgresEscalationRepository,
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
from app.infrastructure.database.repositories.customer_summary_delivery_repository import (
    PostgresCustomerSummaryDeliveryRepository,
)
from app.infrastructure.database.repositories.post_call_summary_repository import (
    PostgresPostCallSummaryRepository,
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
        "complaint_lifecycle_events",
        "customer_summary_deliveries",
        "post_call_summaries",
        "users",
        "call_customers",
        "escalations",
        "emerging_complaint_candidates",
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


def test_conversation_add_rejects_existing_call_id_without_touching_it(session_factory):
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-dup", start_time=0.0)
    repo.add(conversation)
    conversation.add_utterance(
        Utterance(
            utterance_id="u1",
            transcript="my car is still not ready",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=1.0,
        )
    )
    conversation.complete(end_time=5.0)
    repo.save(conversation)

    # A second process/repository instance trying to create the same call.
    with pytest.raises(ConversationAlreadyExistsError):
        PostgresConversationRepository(session_factory).add(
            Conversation(call_id="call-dup", start_time=0.0)
        )

    loaded = repo.get("call-dup")
    assert loaded is not None
    assert loaded.status is ConversationStatus.COMPLETED
    assert loaded.end_time == 5.0
    assert [u.utterance_id for u in loaded.utterances] == ["u1"]



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


# 10. Call history listing ----------------------------------------------------


def _set_created_at(session_factory, call_id, created_at):
    with session_factory() as session, session.begin():
        session.get(ConversationModel, call_id).created_at = created_at


def _created_at(session_factory, call_id):
    with session_factory() as session:
        return session.get(ConversationModel, call_id).created_at


def test_conversation_list_page_orders_newest_created_first_and_paginates(session_factory):
    repo = PostgresConversationRepository(session_factory)
    for index, call_id in enumerate(["call-a", "call-b", "call-c"]):
        repo.save(Conversation(call_id=call_id))
        _set_created_at(session_factory, call_id, datetime(2026, 1, 1, 12, index))

    assert [c.call_id for c in repo.list_page(limit=2, offset=0)] == ["call-c", "call-b"]
    assert [c.call_id for c in repo.list_page(limit=2, offset=2)] == ["call-a"]
    assert repo.list_page(limit=2, offset=3) == ()


def test_conversation_list_page_breaks_created_at_ties_by_call_id(session_factory):
    repo = PostgresConversationRepository(session_factory)
    same_time = datetime(2026, 1, 1, 12, 0)
    for call_id in ["call-b", "call-a"]:
        repo.save(Conversation(call_id=call_id))
        _set_created_at(session_factory, call_id, same_time)

    assert [c.call_id for c in repo.list_page(limit=10, offset=0)] == ["call-a", "call-b"]


def test_conversation_save_preserves_created_at(session_factory):
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-keep")
    repo.save(conversation)
    original = datetime(2026, 1, 1, 9, 30)
    _set_created_at(session_factory, "call-keep", original)

    conversation.add_utterance(
        Utterance(
            utterance_id="u-keep",
            transcript="hello",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=1.0,
        )
    )
    repo.save(conversation)
    conversation.complete(end_time=2.0)
    repo.save(conversation)

    assert _created_at(session_factory, "call-keep") == original


def test_conversation_list_page_loads_completed_calls_with_utterances(session_factory):
    repo = PostgresConversationRepository(session_factory)
    conversation = Conversation(call_id="call-done")
    conversation.add_utterance(
        Utterance(
            utterance_id="u-done",
            transcript="thanks",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=1.0,
        )
    )
    conversation.complete(end_time=3.0)
    repo.save(conversation)

    (loaded,) = repo.list_page(limit=10, offset=0)

    assert loaded.status == ConversationStatus.COMPLETED
    assert loaded.utterance_count == 1
    assert loaded.end_time == 3.0


def test_conversation_counts(session_factory):
    repo = PostgresConversationRepository(session_factory)
    assert repo.count() == 0
    assert repo.count_by_status() == {
        ConversationStatus.ACTIVE: 0,
        ConversationStatus.COMPLETED: 0,
    }

    repo.save(Conversation(call_id="call-1"))
    repo.save(Conversation(call_id="call-2"))
    completed = Conversation(call_id="call-3")
    completed.complete(end_time=1.0)
    repo.save(completed)

    assert repo.count() == 3
    assert repo.count_by_status() == {
        ConversationStatus.ACTIVE: 2,
        ConversationStatus.COMPLETED: 1,
    }


# 11. Post-call summaries -----------------------------------------------------


def _post_call_summary(call_id="call-summary", overall_summary="First summary."):
    return PostCallSummary(
        call_id=call_id,
        overall_summary=overall_summary,
        languages=("en", "ta"),
        sentiment=SentimentResult(SentimentLabel.NEGATIVE, 0.82, "Customer sounded upset."),
        complaints=(
            ComplaintSummary(
                category="Turnaround Time",
                description="Vehicle was late.",
                status=ComplaintCoverageStatus.UNRESOLVED,
                evidence="It was supposed to be ready yesterday.",
                confidence=0.9,
            ),
            ComplaintSummary(
                category="Communication",
                description="Nobody called back.",
                status=ComplaintCoverageStatus.COVERED,
                evidence="No one called me.",
            ),
        ),
        unresolved_issues=("Vehicle was late.",),
        actions_promised=("Call the customer tomorrow.",),
        follow_up_required=True,
        customer_summary="We will call you tomorrow.",
        service_estimate=ServiceEstimate(
            service_name="Brake Pad Replacement",
            currency="INR",
            parts=(EstimatedPart("Brake pad set", 2, Decimal("1400.55")),),
            labour=LabourEstimate(hours=1.5, hourly_rate=Decimal("600.10")),
            estimated_duration_hours=3.0,
        ),
    )


def test_post_call_summary_round_trips_with_nested_data_and_decimals(session_factory):
    repo = PostgresPostCallSummaryRepository(session_factory)
    summary = _post_call_summary()

    repo.add_if_absent(summary)
    loaded = repo.get("call-summary")

    assert loaded == summary
    assert loaded.service_estimate.parts[0].unit_price == Decimal("1400.55")
    assert loaded.service_estimate.labour.hourly_rate == Decimal("600.10")
    assert loaded.service_estimate.estimated_cost == summary.service_estimate.estimated_cost
    assert loaded.complaints[1].confidence is None
    assert repo.get("missing") is None


def test_post_call_summary_without_estimate_round_trips(session_factory):
    repo = PostgresPostCallSummaryRepository(session_factory)
    summary = dataclasses.replace(_post_call_summary(), service_estimate=None)

    repo.add_if_absent(summary)

    assert repo.get("call-summary") == summary


def test_post_call_summary_add_if_absent_keeps_the_first_summary(session_factory):
    repo = PostgresPostCallSummaryRepository(session_factory)
    first = _post_call_summary(overall_summary="First summary.")
    second = _post_call_summary(overall_summary="Second summary.")

    assert repo.add_if_absent(first) == first
    assert repo.add_if_absent(second) == first
    assert repo.get("call-summary").overall_summary == "First summary."


def test_post_call_summary_survives_conversation_rewrites(session_factory):
    conversations = PostgresConversationRepository(session_factory)
    summaries = PostgresPostCallSummaryRepository(session_factory)
    conversation = Conversation(call_id="call-summary")
    conversations.save(conversation)
    summaries.add_if_absent(_post_call_summary())

    conversation.complete(end_time=5.0)
    conversations.save(conversation)

    assert summaries.get("call-summary") == _post_call_summary()


def test_customer_summary_delivery_idempotency_key_is_unique(session_factory):
    repo = PostgresCustomerSummaryDeliveryRepository(session_factory)
    delivery = CustomerSummaryDelivery(
        delivery_id="delivery-1",
        customer_id="cust-1",
        call_id="call-summary",
        channel=MessagingChannel.SMS,
        status=DeliveryStatus.SENT,
        message="Summary",
        idempotency_key="customer-summary:call-summary:cust-1:sms",
    )
    repo.save(delivery)

    assert repo.get_by_idempotency_key(delivery.idempotency_key) == delivery
    with pytest.raises(IntegrityError):
        repo.save(dataclasses.replace(delivery, delivery_id="delivery-2"))
    assert repo.get_by_call_id("call-summary") == (delivery,)


# Caller identity -------------------------------------------------------------


def test_call_customer_link_round_trips_and_updates_in_place(session_factory):
    repo = PostgresCallCustomerRepository(session_factory)
    link = CallCustomerLink(call_id="call-1", caller_number="+919845000001", updated_at=1.0)

    repo.save(link)
    assert repo.get("call-1") == link
    assert repo.get("missing") is None

    matched = link.replace(customer_id="C-1", vehicle_id="V-1", updated_at=2.0)
    repo.save(matched)
    assert repo.get("call-1") == matched


def test_call_customer_link_survives_conversation_rewrites(session_factory):
    conversations = PostgresConversationRepository(session_factory)
    links = PostgresCallCustomerRepository(session_factory)
    conversation = Conversation(call_id="call-link", start_time=0.0)
    conversations.add(conversation)
    links.save(CallCustomerLink(call_id="call-link", caller_number="+919845000001"))

    conversation.complete(end_time=5.0)
    conversations.save(conversation)

    assert links.get("call-link").caller_number == "+919845000001"


# Escalations -----------------------------------------------------------------


def test_escalation_round_trips_updates_in_place_and_lists_by_status(session_factory):
    repo = PostgresEscalationRepository(session_factory)
    signals = (
        EscalationSignal(
            EscalationSignalType.LEGAL_THREAT,
            EscalationLevel.CRITICAL,
            "Customer mentioned a consumer court.",
            "நுகர்வோர் நீதிமன்றம்",
        ),
        EscalationSignal(
            EscalationSignalType.NEGATIVE_TONE, EscalationLevel.WATCH, "Negative tone."
        ),
    )
    open_escalation = Escalation(
        call_id="call-esc",
        level=EscalationLevel.CRITICAL,
        signals=signals,
        status=EscalationStatus.OPEN,
        first_detected_at=10.0,
        updated_at=10.0,
    )

    repo.save(open_escalation)
    assert repo.get("call-esc") == open_escalation
    assert repo.get("missing") is None

    resolved = open_escalation.acknowledge("sup@example.com", 20.0).resolve(
        "sup@example.com", 30.0, "Called back."
    )
    repo.save(resolved)

    assert repo.get("call-esc") == resolved
    assert repo.get_many(["call-esc", "missing"]) == {"call-esc": resolved}
    assert repo.get_many([]) == {}
    assert repo.list_by_status([EscalationStatus.OPEN]) == ()
    assert repo.list_by_status([EscalationStatus.RESOLVED]) == (resolved,)


# Learning loop: re-saving a parent row must not cascade-delete its children.


def _approved_candidate_with_improvement(session_factory):
    specification = ImprovementSpecification(
        component=LearningComponent.COMPLAINT_DETECTION,
        current_behavior="Reviewers corrected 'Turnaround Time' to 'Communication'.",
        proposed_behavior="Tell the two apart.",
        reason="Recurred 2 times.",
    )
    candidate = ImprovementCandidate(
        candidate_id="cand-loop",
        improvement_type=ImprovementType.COMPLAINT_DETECTION,
        title="Improve complaint detection",
        description="Recurring issue.",
        evidence=("e1", "e2"),
        occurrence_count=2,
        confidence=0.5,
        status=ImprovementReviewStatus.APPROVED,
        created_at=100.0,
        reviewed_at=200.0,
        specification=specification,
    )
    improvement = ActiveImprovement(
        improvement_id="imp-loop",
        candidate_id="cand-loop",
        component=LearningComponent.COMPLAINT_DETECTION,
        specification=specification,
        status=ActiveImprovementStatus.ACTIVE,
        activated_at=300.0,
    )
    candidates = PostgresImprovementCandidateRepository(session_factory)
    improvements = PostgresActiveImprovementRepository(session_factory)
    usages = PostgresImprovementUsageRepository(session_factory)
    candidates.save(candidate)
    improvements.save(improvement)
    usages.save(
        ImprovementUsage(
            usage_id="usage-loop",
            improvement_id="imp-loop",
            candidate_id="cand-loop",
            call_id="call-1",
            component=LearningComponent.COMPLAINT_DETECTION,
            output_value="Communication",
            used_at=400.0,
        )
    )
    return candidate, improvement, candidates, improvements, usages


def test_resaving_a_candidate_keeps_its_active_improvement(session_factory):
    candidate, improvement, candidates, improvements, _ = (
        _approved_candidate_with_improvement(session_factory)
    )

    candidates.save(dataclasses.replace(candidate, description="Updated description."))

    assert candidates.get("cand-loop").description == "Updated description."
    assert improvements.get("imp-loop") == improvement


def test_deactivating_an_improvement_keeps_its_usage_history(session_factory):
    _, improvement, _, improvements, usages = _approved_candidate_with_improvement(
        session_factory
    )

    improvements.save(improvement.deactivate(500.0))

    stored = improvements.get("imp-loop")
    assert stored.status is ActiveImprovementStatus.INACTIVE
    assert stored.deactivated_at == 500.0
    assert [u.usage_id for u in usages.list_for_improvement("imp-loop")] == ["usage-loop"]


# Complaint lifecycle queries and history; emerging complaint candidates.


def test_complaint_lifecycle_queries_and_event_history(session_factory):
    from app.domain.complaint_lifecycle import (
        ComplaintLifecycleEvent,
        ComplaintLifecycleRecord,
        ComplaintLifecycleStatus as S,
    )
    from app.infrastructure.database.repositories.complaint_lifecycle_repository import (
        PostgresComplaintLifecycleRepository,
    )

    repo = PostgresComplaintLifecycleRepository(session_factory)
    first = ComplaintLifecycleRecord("a:Cost", "a", "Cost", S.DETECTED, 1.0, 1.0, customer_id="cust")
    second = ComplaintLifecycleRecord("a:Hygiene", "a", "Hygiene", S.RESOLVED, 2.0, 2.0)
    other = ComplaintLifecycleRecord("b:Cost", "b", "Cost", S.FOLLOW_UP, 0.5, 3.0, True, "cust")
    for record in (second, first, other):
        repo.save(record)
    repo.add_event(ComplaintLifecycleEvent("a:Cost", S.DETECTED, 1.0, "system"))
    repo.add_event(ComplaintLifecycleEvent("a:Cost", S.RESOLVED, 5.0, "sup@example.com", "Fixed."))

    assert repo.list_for_call("a") == (first, second)
    assert repo.list_for_customer("cust") == (other, first)
    assert repo.list_by_status([S.RESOLVED]) == (second,)
    events = repo.list_events(["a:Cost", "a:Hygiene"])
    assert list(events) == ["a:Cost"]
    assert [(e.status, e.actor, e.note) for e in events["a:Cost"]] == [
        (S.DETECTED, "system", None),
        (S.RESOLVED, "sup@example.com", "Fixed."),
    ]
    assert repo.list_events([]) == {}


def test_emerging_complaint_candidates_round_trip_and_update_in_place(session_factory):
    from app.domain.emerging_complaint_candidate import (
        EmergingComplaintCandidate,
        EmergingComplaintReviewStatus,
    )
    from app.infrastructure.database.repositories.emerging_complaint_repository import (
        PostgresEmergingComplaintRepository,
    )

    repo = PostgresEmergingComplaintRepository(session_factory)
    candidate = EmergingComplaintCandidate(
        candidate_id="emerging-1",
        proposed_name="Ac Smell",
        description="Smell from the AC.",
        evidence=("ஏசி வாசனை", "ac smells"),
        occurrence_count=2,
        confidence=0.5,
        call_ids=("a", "b"),
    ).first_stored(10.0)

    repo.save(candidate)
    assert repo.get("emerging-1") == candidate
    assert repo.get("missing") is None

    reviewed = candidate.review(
        EmergingComplaintReviewStatus.ACCEPTED, "sup@example.com", 20.0, "Real"
    )
    repo.save(reviewed)

    assert repo.get("emerging-1") == reviewed
    assert repo.list_by_status([EmergingComplaintReviewStatus.PENDING_REVIEW]) == ()
    assert repo.list_by_status([EmergingComplaintReviewStatus.ACCEPTED]) == (reviewed,)
