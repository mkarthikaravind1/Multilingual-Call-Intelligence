import pytest

from app.domain.learning_evidence import EvidenceType, LearningComponent
from app.domain.learning_evidence_repository import InMemoryLearningEvidenceRepository
from app.domain.learning_feedback import FeedbackType, LearningFeedback
from app.domain.learning_observation import LearningObservation
from app.services.learning_evidence_generation_service import (
    LearningEvidenceCallMismatchError,
    LearningEvidenceGenerationService,
)
from app.services.learning_evidence_service import LearningEvidenceService


def build():
    repository = InMemoryLearningEvidenceRepository()
    evidence_service = LearningEvidenceService(repository)
    ids = iter(f"ev-{i}" for i in range(1, 100))
    service = LearningEvidenceGenerationService(
        evidence_service, id_factory=lambda: next(ids), clock=lambda: 500.0
    )
    return service, evidence_service


def observation(
    component: LearningComponent = LearningComponent.COMPLAINT_DETECTION,
    predicted: str = "Turnaround Time",
    call_id: str = "call-1",
    observation_id: str = "obs-1",
) -> LearningObservation:
    return LearningObservation(
        observation_id=observation_id,
        call_id=call_id,
        component=component,
        description="AI output.",
        predicted_value=predicted,
        confidence=0.9,
        created_at=100.0,
    )


def feedback(feedback_type: FeedbackType, **overrides) -> LearningFeedback:
    values = dict(
        feedback_id="fb-1",
        observation_id="obs-1",
        feedback_type=feedback_type,
        corrected_value=None,
        outcome=None,
        created_at=200.0,
        call_id="call-1",
    )
    values.update(overrides)
    return LearningFeedback(**values)  # type: ignore[arg-type]


def test_ai_prediction_only():
    service, _ = build()
    obs = observation(LearningComponent.SENTIMENT_ANALYSIS, "NEGATIVE")

    evidence = service.generate(obs)

    assert evidence.evidence_type is EvidenceType.AI_PREDICTION
    assert evidence.component is LearningComponent.SENTIMENT_ANALYSIS
    assert evidence.call_id == "call-1"
    assert evidence.actual_value == "NEGATIVE"
    assert evidence.expected_value is None
    assert evidence.human_correction is None
    assert evidence.created_at == 500.0


def test_human_correction():
    service, _ = build()

    evidence = service.generate(
        observation(),
        feedback(FeedbackType.HUMAN_CORRECTION, corrected_value="Communication"),
    )

    assert evidence.evidence_type is EvidenceType.HUMAN_CORRECTION
    assert evidence.component is LearningComponent.COMPLAINT_DETECTION
    assert evidence.actual_value == "Turnaround Time"
    assert evidence.expected_value == "Communication"
    assert evidence.human_correction == "Communication"
    assert evidence.call_id == "call-1"


def test_question_effectiveness():
    service, _ = build()
    obs = observation(
        LearningComponent.NEXT_QUESTION, "Was the delivery date communicated?"
    )

    evidence = service.generate(
        obs, feedback(FeedbackType.QUESTION_EFFECTIVENESS, outcome="useful")
    )

    assert evidence.evidence_type is EvidenceType.QUESTION_FEEDBACK
    assert evidence.component is LearningComponent.NEXT_QUESTION
    assert evidence.actual_value == "Was the delivery date communicated?"
    assert evidence.expected_value == "useful"
    assert evidence.human_correction is None


def test_outcome_feedback():
    service, _ = build()
    obs = observation(LearningComponent.ESTIMATION, "Oil Change")

    evidence = service.generate(
        obs, feedback(FeedbackType.OUTCOME, outcome="accepted")
    )

    assert evidence.evidence_type is EvidenceType.OUTCOME
    assert evidence.component is LearningComponent.ESTIMATION
    assert evidence.actual_value == "Oil Change"
    assert evidence.expected_value == "accepted"
    assert evidence.human_correction is None


def test_feedback_without_call_id_uses_observation_call_id():
    service, _ = build()

    evidence = service.generate(
        observation(),
        feedback(FeedbackType.OUTCOME, outcome="accepted", call_id=None),
    )

    assert evidence.call_id == "call-1"


def test_call_id_mismatch_is_rejected_and_nothing_is_stored():
    service, evidence_service = build()

    with pytest.raises(LearningEvidenceCallMismatchError):
        service.generate(
            observation(),
            feedback(
                FeedbackType.HUMAN_CORRECTION,
                corrected_value="Communication",
                call_id="call-2",
            ),
        )

    with pytest.raises(Exception):
        evidence_service.get("ev-1")


def test_feedback_for_different_observation_is_rejected():
    service, _ = build()

    with pytest.raises(ValueError, match="references observation"):
        service.generate(
            observation(),
            feedback(
                FeedbackType.HUMAN_CORRECTION,
                corrected_value="Communication",
                observation_id="obs-other",
            ),
        )


def test_description_is_deterministic_and_free_of_ids_and_times():
    service, _ = build()
    fb_a = feedback(FeedbackType.HUMAN_CORRECTION, corrected_value="Communication")
    fb_b = feedback(
        FeedbackType.HUMAN_CORRECTION,
        corrected_value="Communication",
        feedback_id="fb-2",
        call_id="call-2",
    )

    first = service.generate(observation(), fb_a)
    second = service.generate(
        observation(call_id="call-2", observation_id="obs-1"), fb_b
    )

    assert first.description == second.description
    assert first.description == (
        "AI predicted complaint_detection 'Turnaround Time' and human "
        "corrected it to 'Communication'."
    )
    assert first.evidence_id != second.evidence_id


def test_evidence_is_persisted_through_existing_evidence_service():
    service, evidence_service = build()

    evidence = service.generate(observation())

    assert evidence_service.get(evidence.evidence_id) == evidence


def test_default_id_and_clock_produce_unique_ids():
    evidence_service = LearningEvidenceService(InMemoryLearningEvidenceRepository())
    service = LearningEvidenceGenerationService(evidence_service)

    first = service.generate(observation())
    second = service.generate(observation())

    assert first.evidence_id != second.evidence_id
    assert first.created_at > 0


@pytest.mark.parametrize(
    "fb_type, overrides",
    [
        (FeedbackType.HUMAN_CORRECTION, {"outcome": "useful"}),
    ],
)
def test_human_correction_without_corrected_value_is_rejected(fb_type, overrides):
    service, _ = build()

    with pytest.raises(ValueError, match="corrected_value"):
        service.generate(observation(), feedback(fb_type, **overrides))


def test_invalid_input_types_are_rejected():
    service, _ = build()

    with pytest.raises(TypeError):
        service.generate("not an observation")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        service.generate(observation(), "not feedback")  # type: ignore[arg-type]