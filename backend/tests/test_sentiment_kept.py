"""A sentiment answer that could not be used (confidence 0) never replaces
the tone the call already had: not during the call, and not in the final
analysis after it."""

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.rule_based_provider import RuleBasedQuestionProvider
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
    keeping_earlier,
)
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.domain.utterance import SpeakerRole, Utterance
from app.estimation.default_pricing import DEFAULT_PRICING_CONFIG
from app.estimation.rule_based_provider import RuleBasedEstimationProvider
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.conversation_analysis_service import ConversationAnalysisService
from app.services.conversation_service import ConversationService
from app.services.estimation_service import EstimationService
from app.services.in_memory_conversation_coverage_repository import (
    InMemoryConversationCoverageRepository,
)
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.next_question_service import NextQuestionService
from app.services.post_call_summary_service import PostCallSummaryService
from app.services.sentiment_analysis_service import SentimentAnalysisService

CALL_ID = "call-1"
FRUSTRATED = SentimentResult(SentimentLabel.FRUSTRATED, 0.8, "Fed up with waiting.")
POSITIVE = SentimentResult(SentimentLabel.POSITIVE, 0.9, "Thanked the advisor.")
UNDETERMINED = SentimentResult(SentimentLabel.NEUTRAL, 0.0, "Could not be determined.")


class NoComplaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return []


class SentimentsInTurn(SentimentAnalysisProvider):
    def __init__(self, *results: SentimentResult) -> None:
        self._results = list(results)

    def analyze(self, conversation, learning_context=()):
        return self._results.pop(0)


def _workflow(*sentiments: SentimentResult) -> tuple[CallWorkflowService, CallService]:
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    call_service.start_call(CALL_ID)
    workflow = CallWorkflowService(
        call_service,
        InMemoryConversationCoverageRepository(),
        ConversationAnalysisService(
            ComplaintAnalysisService(NoComplaints()),
            SentimentAnalysisService(SentimentsInTurn(*sentiments)),
        ),
        NextQuestionService(RuleBasedQuestionProvider()),
        EstimationService(RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG)),
        PostCallSummaryService(RuleBasedSummaryProvider()),
    )
    return workflow, call_service


def _say(call_service: CallService, index: int, text: str) -> None:
    call_service.add_utterance(
        CALL_ID,
        Utterance(
            utterance_id=f"u{index}",
            transcript=text,
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=float(index),
            end_time=index + 0.5,
        ),
    )


def test_an_undetermined_result_gives_way_to_an_earlier_one():
    assert keeping_earlier(UNDETERMINED, FRUSTRATED) == FRUSTRATED
    assert keeping_earlier(UNDETERMINED, None) is UNDETERMINED
    assert keeping_earlier(UNDETERMINED, UNDETERMINED) is UNDETERMINED
    # A usable result always replaces the earlier one.
    assert keeping_earlier(POSITIVE, FRUSTRATED) is POSITIVE


def test_a_live_call_keeps_its_tone_through_an_unusable_answer():
    workflow, call_service = _workflow(FRUSTRATED, UNDETERMINED, POSITIVE)

    _say(call_service, 1, "I have been waiting for two hours.")
    assert workflow.analyze_latest_speech(CALL_ID).sentiment == FRUSTRATED
    _say(call_service, 2, "Nobody has told me anything.")
    assert workflow.analyze_latest_speech(CALL_ID).sentiment == FRUSTRATED
    assert workflow.analyze_call(CALL_ID).sentiment == FRUSTRATED
    _say(call_service, 3, "Thank you, that helps.")
    assert workflow.analyze_latest_speech(CALL_ID).sentiment == POSITIVE


def test_the_final_analysis_keeps_the_live_tone_when_its_own_answer_is_unusable():
    workflow, call_service = _workflow(FRUSTRATED, UNDETERMINED)
    _say(call_service, 1, "I have been waiting for two hours.")
    workflow.analyze_latest_speech(CALL_ID)

    workflow.complete_call(CALL_ID, 10.0)

    assert workflow.analyze_call(CALL_ID).sentiment.label is SentimentLabel.FRUSTRATED


def test_a_usable_final_answer_replaces_the_live_tone():
    workflow, call_service = _workflow(FRUSTRATED, POSITIVE)
    _say(call_service, 1, "I have been waiting for two hours.")
    workflow.analyze_latest_speech(CALL_ID)

    workflow.complete_call(CALL_ID, 10.0)

    assert workflow.analyze_call(CALL_ID).sentiment.label is SentimentLabel.POSITIVE


def test_a_call_never_analysed_live_stays_undetermined():
    workflow, call_service = _workflow(UNDETERMINED)
    _say(call_service, 1, "Hello?")

    workflow.complete_call(CALL_ID, 10.0)

    assert workflow.analyze_call(CALL_ID).sentiment.confidence == 0.0
