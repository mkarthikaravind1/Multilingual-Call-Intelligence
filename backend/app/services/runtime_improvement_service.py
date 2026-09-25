import logging

from app.domain.active_improvement import ActiveImprovement
from app.domain.active_improvement_repository import ActiveImprovementRepository
from app.domain.learning_evidence import LearningComponent
from app.domain.runtime_improvement_context import RuntimeImprovementContext

logger = logging.getLogger(__name__)


class RuntimeImprovementService:
    """Read-only bridge between the active-improvement registry and runtime
    AI components. This is the sole point where a learning-retrieval
    failure is isolated, so unavailable learning data never breaks normal
    call processing."""

    def __init__(self, repository: ActiveImprovementRepository) -> None:
        self._repository = repository

    def get_context_for_component(
        self, component: LearningComponent
    ) -> tuple[RuntimeImprovementContext, ...]:
        try:
            improvements = self._repository.list_active_for_component(component)
        except Exception:
            logger.exception(
                "Failed to retrieve active improvements for component %s; "
                "continuing without learning context.",
                component.value,
            )
            return ()
        return tuple(self._to_context(improvement) for improvement in improvements)

    @staticmethod
    def _to_context(improvement: ActiveImprovement) -> RuntimeImprovementContext:
        return RuntimeImprovementContext(
            improvement_id=improvement.improvement_id,
            candidate_id=improvement.candidate_id,
            component=improvement.component,
            specification=improvement.specification,
        )