from dataclasses import dataclass

from sqlalchemy import text
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
from app.infrastructure.database.repositories.post_call_summary_repository import (
    PostgresPostCallSummaryRepository,
)
from app.services.conversation_coverage_repository import ConversationCoverageRepository
from app.services.conversation_repository import ConversationRepository
from app.services.customer_summary_repository import CustomerSummaryDeliveryRepository
from app.services.post_call_summary_repository import PostCallSummaryRepository
from app.domain.user_repository import UserRepository
from app.infrastructure.database.repositories.user_repository import (
    PostgresUserRepository,
)
from app.infrastructure.database.repositories.call_customer_repository import (
    PostgresCallCustomerRepository,
)
from app.services.call_customer_repository import CallCustomerRepository
from app.infrastructure.database.repositories.escalation_repository import (
    PostgresEscalationRepository,
)
from app.services.escalation_repository import EscalationRepository
from app.infrastructure.database.repositories.call_listing_query import (
    PostgresCallListingQuery,
)
from app.services.call_listing import CallListingQuery
from app.infrastructure.database.repositories.emerging_complaint_repository import (
    PostgresEmergingComplaintRepository,
)
from app.services.emerging_complaint_repository import EmergingComplaintRepository
from app.infrastructure.database.repositories.price_list_repository import (
    PostgresPriceListRepository,
)
from app.services.price_list_repository import PriceListRepository
from app.domain.location import LocationRepository
from app.infrastructure.database.repositories.report_source import PostgresReportSource
from app.services.reporting import ReportSource
from app.infrastructure.database.repositories.location_repository import (
    PostgresLocationRepository,
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
    post_call_summary: PostCallSummaryRepository
    user: UserRepository
    call_customer: CallCustomerRepository
    escalation: EscalationRepository
    emerging_complaint: EmergingComplaintRepository
    price_list: PriceListRepository | None = None
    location: LocationRepository | None = None
    # Read model over calls, their complaints and their summaries.
    report_source: ReportSource | None = None
    # Read model over conversations, customers, escalations and complaints.
    call_listing: CallListingQuery | None = None
    session_factory: sessionmaker[Session] | None = None

    def ping(self) -> None:
        """Raise if the database cannot be reached (readiness checks)."""
        if self.session_factory is None:
            return
        with self.session_factory() as session:
            session.execute(text("SELECT 1"))

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
        post_call_summary=PostgresPostCallSummaryRepository(session_factory),
        user=PostgresUserRepository(session_factory),
        call_customer=PostgresCallCustomerRepository(session_factory),
        escalation=PostgresEscalationRepository(session_factory),
        emerging_complaint=PostgresEmergingComplaintRepository(session_factory),
        call_listing=PostgresCallListingQuery(session_factory),
        price_list=PostgresPriceListRepository(session_factory),
        location=PostgresLocationRepository(session_factory),
        report_source=PostgresReportSource(session_factory),
        session_factory=session_factory,
    )


def build_production_repositories(settings: Settings | None = None) -> PostgresRepositories:
    """Entry point used by the application at startup. Raises
    DatabaseNotConfiguredError (see app.infrastructure.database.engine) if
    DATABASE_URL is missing — production never falls back to in-memory."""
    settings = settings or get_settings()
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    return build_postgres_repositories(session_factory)