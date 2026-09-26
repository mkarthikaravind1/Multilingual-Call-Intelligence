from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.domain.active_improvement_repository import ActiveImprovementRepository
from app.domain.complaint_customer_history_repository import (
    ComplaintCustomerHistoryRepository,
)
from app.domain.complaint_lifecycle_repository import ComplaintLifecycleRepository
from app.domain.improvement_candidate_repository import ImprovementCandidateRepository
from app.domain.improvement_usage_repository import ImprovementUsageRepository
from app.domain.learning_evidence_repository import LearningEvidenceRepository
from app.domain.learning_feedback_repository import LearningFeedbackRepository
from app.domain.learning_observation_repository import LearningObservationRepository
from app.infrastructure.database.engine import build_engine, build_session_factory
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
from app.infrastructure.database.repositories.customer_summary_delivery_repository import (
    PostgresCustomerSummaryDeliveryRepository,
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
from app.services.conversation_coverage_repository import ConversationCoverageRepository
from app.services.conversation_repository import ConversationRepository
from app.services.customer_summary_repository import CustomerSummaryDeliveryRepository
from app.domain.user_repository import UserRepository
from app.infrastructure.database.repositories.user_repository import (
    PostgresUserRepository,
)

@dataclass(frozen=True)
class PostgresRepositories:
    """Every repository implementation backed by PostgreSQL, sharing one
    session factory (and therefore one engine/connection pool)."""

    conversation: ConversationRepository
    conversation_coverage: ConversationCoverageRepository
    learning_evidence: LearningEvidenceRepository
    learning_observation: LearningObservationRepository
    learning_feedback: LearningFeedbackRepository
    improvement_candidate: ImprovementCandidateRepository
    active_improvement: ActiveImprovementRepository
    improvement_usage: ImprovementUsageRepository
    complaint_lifecycle: ComplaintLifecycleRepository
    complaint_customer_history: ComplaintCustomerHistoryRepository
    customer_summary_delivery: CustomerSummaryDeliveryRepository
    user: UserRepository

def build_postgres_repositories(
    session_factory: sessionmaker[Session],
) -> PostgresRepositories:
    return PostgresRepositories(
        conversation=PostgresConversationRepository(session_factory),
        conversation_coverage=PostgresConversationCoverageRepository(session_factory),
        learning_evidence=PostgresLearningEvidenceRepository(session_factory),
        learning_observation=PostgresLearningObservationRepository(session_factory),
        learning_feedback=PostgresLearningFeedbackRepository(session_factory),
        improvement_candidate=PostgresImprovementCandidateRepository(session_factory),
        active_improvement=PostgresActiveImprovementRepository(session_factory),
        improvement_usage=PostgresImprovementUsageRepository(session_factory),
        complaint_lifecycle=PostgresComplaintLifecycleRepository(session_factory),
        complaint_customer_history=PostgresComplaintCustomerHistoryRepository(session_factory),
        customer_summary_delivery=PostgresCustomerSummaryDeliveryRepository(session_factory),
        user=PostgresUserRepository(session_factory),
    )


def build_production_repositories(settings: Settings | None = None) -> PostgresRepositories:
    """Entry point used by the application at startup. Raises
    DatabaseNotConfiguredError (see app.infrastructure.database.engine) if
    DATABASE_URL is missing — production never falls back to in-memory."""
    settings = settings or get_settings()
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    return build_postgres_repositories(session_factory)