import logging
from typing import Protocol

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


class ComponentUsageRecorder(Protocol):
    def record_component_usage(
        self,
        call_id: str,
        contexts: tuple[RuntimeImprovementContext, ...],
        output_value: str,
    ) -> None: ...


class ComponentLearning:
    """Runtime learning for one AI component: which approved improvements
    apply to it, and a record of the output they influenced. Neither step
    may break call processing."""

    def __init__(
        self,
        component: LearningComponent,
        runtime_improvement_service: RuntimeImprovementService,
        usage_recorder: ComponentUsageRecorder | None = None,
    ) -> None:
        self._component = component
        self._runtime_improvement_service = runtime_improvement_service
        self._usage_recorder = usage_recorder

    def contexts(self) -> tuple[RuntimeImprovementContext, ...]:
        return self._runtime_improvement_service.get_context_for_component(
            self._component
        )

    def record_usage(
        self,
        call_id: str,
        contexts: tuple[RuntimeImprovementContext, ...],
        output_value: str,
    ) -> None:
        if self._usage_recorder is None or not contexts:
            return
        try:
            self._usage_recorder.record_component_usage(call_id, contexts, output_value)
        except Exception:
            logger.exception(
                "Failed to record %s improvement usage for call %r; continuing.",
                self._component.value,
                call_id,
            )