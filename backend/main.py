"""Application entrypoint.

Production always uses PostgreSQL-backed repositories (built from
DATABASE_URL) — see app.composition.database. Tests use in-memory
repositories directly and never import this module.
"""

import dataclasses
import logging

import uvicorn

from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.composition.database import build_production_repositories
from app.composition.providers import (
    create_complaint_provider,
    create_emerging_complaint_provider,
    create_escalation_provider,
    create_llm_client,
    create_question_provider,
    create_sentiment_provider,
)
from app.core.config import get_settings
from app.core.production_checks import check_configuration
from app.observability.logging import configure_logging

logger = logging.getLogger("app")


def build_app():
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    check_configuration(settings, logger)
    repositories = build_production_repositories(settings)

    llm_client = create_llm_client(settings)
    services = build_api_services(
        complaint_provider=create_complaint_provider(llm_client, settings),
        sentiment_provider=create_sentiment_provider(llm_client, settings),
        question_provider=create_question_provider(llm_client, settings),
        settings=settings,
        conversation_repository=repositories.conversation,
        coverage_repository=repositories.conversation_coverage,
        evidence_repository=repositories.learning_evidence,
        observation_repository=repositories.learning_observation,
        candidate_repository=repositories.improvement_candidate,
        active_improvement_repository=repositories.active_improvement,
        usage_repository=repositories.improvement_usage,
        feedback_repository=repositories.learning_feedback,
        user_repository=repositories.user,
        post_call_summary_repository=repositories.post_call_summary,
        customer_summary_delivery_repository=repositories.customer_summary_delivery,
        call_customer_repository=repositories.call_customer,
        escalation_repository=repositories.escalation,
        escalation_provider=create_escalation_provider(llm_client, settings),
        complaint_lifecycle_repository=repositories.complaint_lifecycle,
        emerging_complaint_repository=repositories.emerging_complaint,
        call_listing_query=repositories.call_listing,
        emerging_complaint_provider=create_emerging_complaint_provider(llm_client, settings),
    )
    services = dataclasses.replace(
        services,
        health_checks={"database": repositories.ping, **services.health_checks},
    )
    return create_app(services)


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, proxy_headers=True, log_config=None)