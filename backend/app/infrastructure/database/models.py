"""SQLAlchemy ORM models (persistence layer).

These mirror the domain dataclasses in app.domain / app.services but are a
separate set of classes: the domain layer must never import SQLAlchemy, and
these models carry no business logic. Repositories map ORM <-> domain.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.infrastructure.database.base import Base


class ConversationModel(Base):
    __tablename__ = "conversations"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Persistence-only: orders call history; not part of the domain model.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    # NULL: not recorded (see Conversation).
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    location_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    executive_user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    utterances: Mapped[list["UtteranceModel"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="UtteranceModel.start_time, UtteranceModel.utterance_id",
    )


class UtteranceModel(Base):
    __tablename__ = "utterances"

    utterance_id: Mapped[str] = mapped_column(String, primary_key=True)
    call_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.call_id", ondelete="CASCADE"), nullable=False
    )
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_role: Mapped[str] = mapped_column(String, nullable=False)
    languages: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The line's tone (a SentimentLabel); NULL until it is rated.
    sentiment: Mapped[str | None] = mapped_column(String, nullable=True)
    sentiment_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    conversation: Mapped["ConversationModel"] = relationship(back_populates="utterances")

    __table_args__ = (Index("ix_utterances_call_id", "call_id"),)


class ConversationCoverageModel(Base):
    __tablename__ = "conversation_coverages"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)

    complaints: Mapped[list["ComplaintCoverageModel"]] = relationship(
        back_populates="conversation_coverage",
        cascade="all, delete-orphan",
    )


class ComplaintCoverageModel(Base):
    __tablename__ = "complaint_coverages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversation_coverages.call_id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)

    conversation_coverage: Mapped["ConversationCoverageModel"] = relationship(
        back_populates="complaints"
    )

    __table_args__ = (
        UniqueConstraint("call_id", "category", name="uq_coverage_call_category"),
        Index("ix_complaint_coverages_call_id", "call_id"),
    )


class LearningEvidenceModel(Base):
    __tablename__ = "learning_evidence"

    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    call_id: Mapped[str] = mapped_column(String, nullable=False)
    evidence_type: Mapped[str] = mapped_column(String, nullable=False)
    component: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (Index("ix_learning_evidence_call_id", "call_id"),)


class LearningObservationModel(Base):
    __tablename__ = "learning_observations"

    observation_id: Mapped[str] = mapped_column(String, primary_key=True)
    call_id: Mapped[str] = mapped_column(String, nullable=False)
    component: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("ix_learning_observations_call_id", "call_id"),)


class LearningFeedbackModel(Base):
    __tablename__ = "learning_feedback"

    feedback_id: Mapped[str] = mapped_column(String, primary_key=True)
    observation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("learning_observations.observation_id", ondelete="CASCADE"),
        nullable=False,
    )
    feedback_type: Mapped[str] = mapped_column(String, nullable=False)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_learning_feedback_observation_id", "observation_id"),
        Index("ix_learning_feedback_call_id", "call_id"),
    )


class ImprovementCandidateModel(Base):
    __tablename__ = "improvement_candidates"

    candidate_id: Mapped[str] = mapped_column(String, primary_key=True)
    improvement_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    reviewed_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    spec_component: Mapped[str | None] = mapped_column(String, nullable=True)
    spec_current_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_proposed_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ActiveImprovementModel(Base):
    __tablename__ = "active_improvements"

    improvement_id: Mapped[str] = mapped_column(String, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("improvement_candidates.candidate_id", ondelete="CASCADE"),
        nullable=False,
    )
    component: Mapped[str] = mapped_column(String, nullable=False)

    spec_component: Mapped[str] = mapped_column(String, nullable=False)
    spec_current_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    spec_proposed_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    spec_reason: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String, nullable=False)
    activated_at: Mapped[float] = mapped_column(Float, nullable=False)
    deactivated_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("ix_active_improvements_candidate_id", "candidate_id"),)


class ImprovementUsageModel(Base):
    __tablename__ = "improvement_usages"

    usage_id: Mapped[str] = mapped_column(String, primary_key=True)
    improvement_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("active_improvements.improvement_id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[str] = mapped_column(String, nullable=False)
    call_id: Mapped[str] = mapped_column(String, nullable=False)
    component: Mapped[str] = mapped_column(String, nullable=False)
    output_value: Mapped[str] = mapped_column(Text, nullable=False)
    used_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_improvement_usages_improvement_id", "improvement_id"),
        Index("ix_improvement_usages_call_id", "call_id"),
    )


class ComplaintLifecycleRecordModel(Base):
    __tablename__ = "complaint_lifecycle_records"

    complaint_id: Mapped[str] = mapped_column(String, primary_key=True)
    call_id: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    first_detected_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    follow_up_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_complaint_lifecycle_call_id", "call_id"),
        Index("ix_complaint_lifecycle_customer_id", "customer_id"),
        Index("ix_complaint_lifecycle_status", "status"),
    )


class ComplaintLifecycleEventModel(Base):
    # Append-only history of a complaint's status changes. No foreign key
    # to the records table.
    __tablename__ = "complaint_lifecycle_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    complaint_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    at: Mapped[float] = mapped_column(Float, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_complaint_lifecycle_events_complaint_id", "complaint_id"),)


class CustomerSummaryDeliveryModel(Base):
    __tablename__ = "customer_summary_deliveries"

    delivery_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, nullable=False)
    call_id: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_customer_summary_deliveries_call_id", "call_id"),
        Index("ix_customer_summary_deliveries_customer_id", "customer_id"),
        Index("ix_customer_summary_deliveries_idempotency_key", "idempotency_key"),
    )


class PostCallSummaryModel(Base):
    # Keyed by call_id without a foreign key (from when saving a call
    # deleted and re-inserted its row, which must not remove the summary).
    __tablename__ = "post_call_summaries"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    overall_summary: Mapped[str] = mapped_column(Text, nullable=False)
    customer_summary: Mapped[str] = mapped_column(Text, nullable=False)
    languages: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sentiment_label: Mapped[str] = mapped_column(String, nullable=False)
    sentiment_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    sentiment_evidence: Mapped[str] = mapped_column(Text, nullable=False)
    complaints: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    unresolved_issues: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    actions_promised: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    follow_up_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    service_estimate: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserModel(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    # Sessions signed in before this no longer count (see User).
    password_changed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    location_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dial_target: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)

    __table_args__ = (Index("ix_users_email", "email"),)


class LocationModel(Base):
    __tablename__ = "locations"

    location_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    phone_number: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class CallCustomerModel(Base):
    # Keyed by call_id without a foreign key (from when saving a call
    # deleted and re-inserted its row, which must not remove this link).
    __tablename__ = "call_customers"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    caller_number: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    vehicle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    # Snapshot of the CRM record, for listing and searching calls.
    customer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    vehicle_registration: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_call_customers_customer_id", "customer_id"),
        Index("ix_call_customers_caller_number", "caller_number"),
    )


class EscalationModel(Base):
    # One row per escalated call, keyed by call_id without a foreign key
    # (from when saving a call deleted and re-inserted its row).
    __tablename__ = "escalations"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    signals: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    first_detected_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String, nullable=True)
    acknowledged_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_escalations_status", "status"),)


class EmergingComplaintCandidateModel(Base):
    # One row per discovered theme; candidate ids are stable, so each
    # discovery run updates the same row.
    __tablename__ = "emerging_complaint_candidates"

    candidate_id: Mapped[str] = mapped_column(String, primary_key=True)
    proposed_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    call_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    related_category: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    first_seen_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_seen_at: Mapped[float] = mapped_column(Float, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The complaint category an accepted theme is detected as.
    category_name: Mapped[str | None] = mapped_column(String, nullable=True)
    category_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_emerging_complaint_candidates_status", "status"),
        # Two accepted themes may not share a category name (ignoring case),
        # even when accepted at once on different API instances.
        Index(
            "uq_emerging_complaint_candidates_accepted_category",
            func.lower(category_name),
            unique=True,
            postgresql_where=text("status = 'accepted'"),
            sqlite_where=text("status = 'accepted'"),
        ),
    )


class PriceListVersionModel(Base):
    # Every saved version of the price list; the newest is in use. Rows and
    # settings are kept as JSON exactly as the supervisor gave them.
    __tablename__ = "price_list_versions"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False)
    rows: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
