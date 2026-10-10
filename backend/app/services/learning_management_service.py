import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import uuid4

from app.ai.sentiment.provider import SentimentLabel
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.active_improvement import ActiveImprovement
from app.domain.improvement_candidate import ImprovementCandidate
from app.domain.improvement_candidate_repository import ImprovementCandidateRepository
from app.domain.improvement_effectiveness import (
    ImprovementEffectivenessResult,
    ImprovementEffectMeasure,
)
from app.domain.learning_evidence import LearningComponent, LearningEvidence
from app.domain.learning_feedback import FeedbackSource, FeedbackType, LearningFeedback
from app.domain.learning_observation import LearningObservation
from app.domain.learning_pattern import LearningPattern
from app.services.improvement_application_service import ImprovementApplicationService
from app.services.improvement_effectiveness_service import ImprovementEffectivenessService
from app.services.learning_candidate_generation_service import (
    LearningCandidateGenerationService,
)
from app.services.learning_evidence_generation_service import (
    LearningEvidenceGenerationService,
)
from app.services.learning_evidence_service import LearningEvidenceService
from app.services.learning_feedback_service import LearningFeedbackService
from app.services.learning_human_review_service import LearningHumanReviewService
from app.services.learning_observation_service import (
    LearningObservationNotFoundError,
    LearningObservationService,
)
from app.services.learning_pattern_discovery_service import (
    LearningPatternDiscoveryService,
)

logger = logging.getLogger(__name__)

# Correction meaning "the AI flagged a complaint that the customer never raised".
NO_COMPLAINT_CORRECTION = "No complaint"

QUESTION_HELPFUL = "helpful"
QUESTION_NOT_HELPFUL = "not_helpful"
QUESTION_OUTCOMES = (QUESTION_HELPFUL, QUESTION_NOT_HELPFUL)

MAX_FEEDBACK_TEXT_LENGTH = 500


def correction_options(
    component: LearningComponent,
    complaint_categories: Sequence[str] = COMPLAINT_CATEGORIES,
) -> tuple[str, ...]:
    """The values a correction may take; empty means free text.
    complaint_categories: the categories detection can report now."""
    if component is LearningComponent.COMPLAINT_DETECTION:
        return (*complaint_categories, NO_COMPLAINT_CORRECTION)
    if component is LearningComponent.SENTIMENT_ANALYSIS:
        return tuple(label.value for label in SentimentLabel)
    return ()


class CandidateNotFoundError(Exception):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(f"No improvement candidate found with id: {candidate_id!r}")
        self.candidate_id = candidate_id


class CandidateReviewConflictError(Exception):
    pass


class LearningFeedbackConflictError(Exception):
    """Feedback was already given for this AI output."""


class InvalidLearningFeedbackError(ValueError):
    pass


@dataclass(frozen=True)
class CallObservation:
    observation: LearningObservation
    feedback: LearningFeedback | None
    correction_options: tuple[str, ...]


@dataclass(frozen=True)
class ImprovementOverview:
    improvement: ActiveImprovement
    effectiveness: ImprovementEffectivenessResult
    # Whether reviewers correct the output less often since it went live.
    effect: ImprovementEffectMeasure | None = None


class LearningManagementService:
    """API-facing facade for the self-learning loop:

    AI output (observation) -> human feedback -> evidence -> patterns ->
    candidates -> human review -> active improvement -> runtime guidance.

    The loop collaborators are optional so read-only uses (and older callers)
    can build it with the first four arguments only.
    """

    def __init__(
        self,
        evidence_service: LearningEvidenceService,
        pattern_discovery: LearningPatternDiscoveryService,
        candidate_repository: ImprovementCandidateRepository,
        review_service: LearningHumanReviewService,
        observation_service: LearningObservationService | None = None,
        feedback_service: LearningFeedbackService | None = None,
        evidence_generation: LearningEvidenceGenerationService | None = None,
        candidate_generation: LearningCandidateGenerationService | None = None,
        application_service: ImprovementApplicationService | None = None,
        effectiveness_service: ImprovementEffectivenessService | None = None,
        complaint_categories: Callable[[], Sequence[str]] | None = None,
    ) -> None:
        self._evidence_service = evidence_service
        # The complaint categories a correction may name (built-ins plus
        # accepted emerging themes); the built-ins when None.
        self._complaint_categories = complaint_categories or (lambda: COMPLAINT_CATEGORIES)
        self._pattern_discovery = pattern_discovery
        self._candidate_repository = candidate_repository
        self._review_service = review_service
        self._observation_service = observation_service
        self._feedback_service = feedback_service
        self._evidence_generation = evidence_generation
        self._candidate_generation = candidate_generation
        self._application_service = application_service
        self._effectiveness_service = effectiveness_service
        # Serialises the "already has feedback?" check with the write.
        self._feedback_lock = threading.Lock()

    # --- Candidates ---

    def list_candidates(self) -> tuple[ImprovementCandidate, ...]:
        return self._candidate_repository.list_all()

    def get_candidate(self, candidate_id: str) -> ImprovementCandidate:
        candidate = self._candidate_repository.get(candidate_id)
        if candidate is None:
            raise CandidateNotFoundError(candidate_id)
        return candidate

    def approve(self, candidate_id: str) -> ImprovementCandidate:
        """Approve a pending candidate and activate it for runtime use.

        Approval and activation succeed together: if activation fails, the
        candidate is restored to pending review so it can be approved again.
        """
        candidate = self.get_candidate(candidate_id)
        try:
            approved = self._review_service.approve(candidate)
        except ValueError as exc:
            raise CandidateReviewConflictError(str(exc)) from exc

        if self._application_service is None:
            return approved
        if approved.specification is None:
            logger.warning(
                "Candidate %r was approved without a specification; nothing to activate.",
                candidate_id,
            )
            return approved

        try:
            self._application_service.activate(approved)
        except Exception:
            self._candidate_repository.save(candidate)
            raise
        return approved

    def reject(self, candidate_id: str) -> ImprovementCandidate:
        candidate = self.get_candidate(candidate_id)
        try:
            return self._review_service.reject(candidate)
        except ValueError as exc:
            raise CandidateReviewConflictError(str(exc)) from exc

    # --- Evidence and patterns ---

    def list_patterns(self) -> list[LearningPattern]:
        return self._pattern_discovery.discover()

    def list_evidence(
        self, limit: int | None = None, offset: int = 0
    ) -> tuple[LearningEvidence, ...]:
        """With a limit: that many, newest first. Without: all of it."""
        if limit is None:
            return self._evidence_service.list_all()
        return self._evidence_service.list_page(limit, offset)

    def count_evidence(self) -> int:
        return self._evidence_service.count()

    # --- Feedback on a call's AI output ---

    def list_call_observations(self, call_id: str) -> tuple[CallObservation, ...]:
        observation_service = self._require(self._observation_service, "observations")
        feedback_service = self._require(self._feedback_service, "feedback")

        feedback_by_observation: dict[str, LearningFeedback] = {}
        for feedback in sorted(
            feedback_service.get_for_call(call_id), key=lambda f: f.created_at
        ):
            feedback_by_observation.setdefault(feedback.observation_id, feedback)

        return tuple(
            CallObservation(
                observation=observation,
                feedback=feedback_by_observation.get(observation.observation_id),
                correction_options=correction_options(
                    observation.component, self._complaint_categories()
                ),
            )
            for observation in sorted(
                observation_service.get_for_call(call_id),
                key=lambda o: (o.created_at, o.observation_id),
            )
        )

    def submit_feedback(
        self,
        call_id: str,
        observation_id: str,
        feedback_type: FeedbackType,
        corrected_value: str | None = None,
        outcome: str | None = None,
        notes: str | None = None,
        source: FeedbackSource = FeedbackSource.ICR,
        created_by: str | None = None,
    ) -> LearningFeedback:
        """Record one human judgement of an AI output, turn it into learning
        evidence and refresh the improvement candidates it may support.
        created_by: the user giving it."""
        observation_service = self._require(self._observation_service, "observations")
        feedback_service = self._require(self._feedback_service, "feedback")
        evidence_generation = self._require(self._evidence_generation, "evidence")

        observation = observation_service.get(observation_id)
        if observation.call_id != call_id:
            # Do not reveal that the observation exists on another call.
            raise LearningObservationNotFoundError(observation_id)

        corrected_value, outcome, notes = _validated_feedback(
            observation,
            feedback_type,
            corrected_value,
            outcome,
            notes,
            correction_options(observation.component, self._complaint_categories()),
        )

        with self._feedback_lock:
            if feedback_service.get_for_observation(observation_id):
                raise LearningFeedbackConflictError(
                    f"Feedback was already given for observation {observation_id!r}."
                )
            feedback = feedback_service.record(
                feedback_id=f"feedback-{uuid4()}",
                call_id=call_id,
                observation_id=observation_id,
                feedback_type=feedback_type,
                created_at=time.time(),
                corrected_value=corrected_value,
                outcome=outcome,
                original_value=observation.predicted_value,
                source=source,
                notes=notes,
                created_by=created_by,
            )
        evidence_generation.generate(observation, feedback)
        self._refresh_candidates()
        return feedback

    def _refresh_candidates(self) -> None:
        # Candidates are derived from stored evidence, so a failure here only
        # delays them until the next refresh; the feedback itself is kept.
        if self._candidate_generation is None:
            return
        try:
            self._candidate_generation.refresh(
                self._pattern_discovery.signals(), self._pattern_discovery.output_calls()
            )
        except Exception:
            logger.exception("Refreshing improvement candidates failed")

    # --- Active improvements ---

    def list_improvements(self) -> tuple[ImprovementOverview, ...]:
        application_service = self._require(self._application_service, "improvements")
        effectiveness_service = self._require(self._effectiveness_service, "effectiveness")
        return tuple(
            ImprovementOverview(
                improvement=improvement,
                effectiveness=effectiveness_service.evaluate(improvement.improvement_id),
                effect=self._effect(improvement),
            )
            for improvement in sorted(
                application_service.list_all(),
                key=lambda i: i.activated_at,
                reverse=True,
            )
        )

    def deactivate_improvement(self, improvement_id: str) -> ImprovementOverview:
        application_service = self._require(self._application_service, "improvements")
        effectiveness_service = self._require(self._effectiveness_service, "effectiveness")
        improvement = application_service.deactivate(improvement_id)
        return ImprovementOverview(
            improvement=improvement,
            effectiveness=effectiveness_service.evaluate(improvement_id),
            effect=self._effect(improvement),
        )

    def _effect(self, improvement: ActiveImprovement) -> ImprovementEffectMeasure | None:
        if self._effectiveness_service is None:
            return None
        try:
            candidate = self._candidate_repository.get(improvement.candidate_id)
            return self._effectiveness_service.measure_effect(
                improvement.component,
                () if candidate is None else candidate.evidence,
                improvement.activated_at,
                improvement.deactivated_at,
            )
        except Exception:
            # A figure for the reviewer; never a reason to hide the list.
            logger.exception(
                "Measuring the effect of improvement %r failed", improvement.improvement_id
            )
            return None

    @staticmethod
    def _require(collaborator, name: str):
        if collaborator is None:
            raise RuntimeError(f"Learning {name} are not configured.")
        return collaborator


def _clean_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_FEEDBACK_TEXT_LENGTH:
        raise InvalidLearningFeedbackError(
            f"{field_name} must be at most {MAX_FEEDBACK_TEXT_LENGTH} characters."
        )
    return value


def _validated_feedback(
    observation: LearningObservation,
    feedback_type: FeedbackType,
    corrected_value: str | None,
    outcome: str | None,
    notes: str | None,
    options: tuple[str, ...] | None = None,
) -> tuple[str | None, str | None, str | None]:
    corrected_value = _clean_text(corrected_value, "corrected_value")
    outcome = _clean_text(outcome, "outcome")
    notes = _clean_text(notes, "notes")

    if feedback_type is FeedbackType.HUMAN_CORRECTION:
        if corrected_value is None:
            raise InvalidLearningFeedbackError("A correction needs corrected_value.")
        if options is None:
            options = correction_options(observation.component)
        if options and corrected_value not in options:
            raise InvalidLearningFeedbackError(
                f"corrected_value must be one of: {', '.join(options)}."
            )
        if corrected_value.casefold() == observation.predicted_value.strip().casefold():
            raise InvalidLearningFeedbackError(
                "corrected_value matches the AI output; there is nothing to correct."
            )
        return corrected_value, None, notes

    if feedback_type is FeedbackType.QUESTION_EFFECTIVENESS:
        if observation.component is not LearningComponent.NEXT_QUESTION:
            raise InvalidLearningFeedbackError(
                "Question feedback applies only to suggested questions."
            )
        if outcome not in QUESTION_OUTCOMES:
            raise InvalidLearningFeedbackError(
                f"outcome must be one of: {', '.join(QUESTION_OUTCOMES)}."
            )
        return None, outcome, notes

    raise InvalidLearningFeedbackError(
        f"Unsupported feedback type: {feedback_type.value}."
    )
