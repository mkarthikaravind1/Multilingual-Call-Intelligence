from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.utterance import SpeakerRole, Utterance
from app.services.next_question_service import NextQuestionService


class FakeProvider(QuestionSuggestionProvider):
    def __init__(self) -> None:
        self.received_context: QuestionGenerationContext | None = None

    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        self.received_context = context
        return QuestionSuggestion(
            question="fake question",
            target_category=context.category,
            priority=1,
            reason="fake reason",
            source=SuggestionSource.MANUAL,
            confidence=0.5,
        )


def _coverage_with(statuses: dict[str, str]) -> ConversationCoverage:
    coverage = ConversationCoverage(call_id="call-1")
    for category, status in statuses.items():
        complaint = coverage.add(category)
        if status == "detected":
            complaint.detect()
        elif status == "probed":
            complaint.detect()
            complaint.probe()
        elif status == "resolved":
            complaint.detect()
            complaint.probe()
            complaint.cover()
            complaint.resolve()
        elif status == "unresolved":
            complaint.detect()
            complaint.probe()
            complaint.cover()
            complaint.mark_unresolved()
    return coverage


def test_detected_complaint_is_sent_to_provider():
    provider = FakeProvider()
    coverage = _coverage_with({"Cost": "detected"})

    suggestion = NextQuestionService(provider).suggest_next_question(coverage)

    assert suggestion is not None
    assert provider.received_context is not None


def test_probed_complaint_is_sent_to_provider():
    provider = FakeProvider()
    coverage = _coverage_with({"Cost": "probed"})

    suggestion = NextQuestionService(provider).suggest_next_question(coverage)

    assert suggestion is not None


def test_resolved_complaint_not_selected():
    provider = FakeProvider()
    coverage = _coverage_with({"Cost": "resolved"})

    suggestion = NextQuestionService(provider).suggest_next_question(coverage)

    assert suggestion is None
    assert provider.received_context is None


def test_unresolved_complaint_not_selected():
    provider = FakeProvider()
    coverage = _coverage_with({"Cost": "unresolved"})

    suggestion = NextQuestionService(provider).suggest_next_question(coverage)

    assert suggestion is None
    assert provider.received_context is None


def test_no_actionable_complaint_returns_none():
    provider = FakeProvider()
    coverage = _coverage_with({})

    suggestion = NextQuestionService(provider).suggest_next_question(coverage)

    assert suggestion is None


def test_provider_receives_correct_category_and_status():
    provider = FakeProvider()
    coverage = _coverage_with({"Hygiene": "detected"})

    NextQuestionService(provider).suggest_next_question(coverage)

    assert provider.received_context.category == "Hygiene" # type: ignore
    assert provider.received_context.status.value == "detected" # type: ignore


def test_provider_receives_utterances():
    provider = FakeProvider()
    coverage = _coverage_with({"Cost": "detected"})
    utterance = Utterance(
        utterance_id="1",
        transcript="The bill was too high",
        speaker_role=SpeakerRole.CUSTOMER,
        languages=("en",),
        start_time=0.0,
        end_time=2.0,
    )

    NextQuestionService(provider).suggest_next_question(coverage, utterances=(utterance,))

    assert provider.received_context.utterances == (utterance,) # type: ignore


def test_service_does_not_depend_on_rule_based_provider():
    import app.services.next_question_service as module

    assert "RuleBasedQuestionProvider" not in dir(module)

def test_every_open_complaint_is_offered_built_ins_first_in_their_order():
    provider = FakeProvider()
    service = NextQuestionService(
        provider, category_descriptions=lambda: {"Wiper Noise": "Wipers squeak after a service."}
    )
    coverage = _coverage_with(
        {
            "Wiper Noise": "detected",
            "Turnaround Time": "detected",
            "Cost": "probed",
            "Hygiene": "resolved",
        }
    )

    service.suggest_next_question(coverage, previous_question="What did the bill say?")

    context = provider.received_context
    assert context is not None
    assert [(c.category, c.status.value) for c in context.open_complaints] == [
        ("Cost", "probed"),
        ("Turnaround Time", "detected"),
        ("Wiper Noise", "detected"),
    ]
    assert context.open_complaints[2].description == "Wipers squeak after a service."
    assert context.category == "Cost"  # the rule-based fallback's choice is unchanged
    assert context.previous_question == "What did the bill say?"


def test_a_failing_category_catalog_does_not_stop_suggestions():
    def broken():
        raise RuntimeError("database down")

    provider = FakeProvider()
    NextQuestionService(provider, category_descriptions=broken).suggest_next_question(
        _coverage_with({"Cost": "detected"})
    )

    assert provider.received_context is not None
    assert provider.received_context.open_complaints[0].description is None
