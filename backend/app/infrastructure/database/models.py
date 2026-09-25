"""SQLAlchemy ORM models (persistence layer).

These mirror the domain dataclasses in app.domain / app.services but are a
separate set of classes: the domain layer must never import SQLAlchemy, and
these models carry no business logic. Repositories map ORM <-> domain.
"""

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base


class ConversationModel(Base):
    __tablename__ = "conversations"

    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)

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
    )

class UserModel(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (Index("ix_users_email", "email"),)