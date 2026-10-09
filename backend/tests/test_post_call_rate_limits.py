"""Post-call processing waits out a short LLM rate limit instead of leaving
the call to the repair job; a long one (the daily limit) is not waited for."""

import httpx
import pytest
from groq import RateLimitError

from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.llm.client import LLMRateLimitedError, LLMRequest
from app.ai.llm.groq_client import GroqClientError, GroqLLMClient, GroqRateLimitedError
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.ai.summary.provider import SummaryGenerationProvider
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
from app.ai.question.rule_based_provider import RuleBasedQuestionProvider

CALL_ID = "call-1"


# ---- Groq's "try again in" becomes a wait ----


def _rate_limit(message: str, retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://x"))
    return RateLimitError(message, response=response, body=None)


@pytest.mark.parametrize(
    ("message", "header", "seconds"),
    [
        ("Rate limit reached ... Please try again in 1.37s. Need more tokens?", None, 1.37),
        ("Rate limit reached ... Please try again in 1m27.696s. Need more", None, 87.696),
        ("Rate limit reached ... Please try again in 450ms.", None, 0.45),
        ("Rate limit reached ... Please try again in 1h2m3s.", None, 3723.0),
        ("Rate limit reached.", "12", 12.0),
        ("Rate limit reached.", None, None),
    ],
)
def test_a_groq_rate_limit_carries_how_long_to_wait(message, header, seconds):
    class FakeCompletions:
        def create(self, **kwargs):
            raise _rate_limit(message, header)

    client = object.__new__(GroqLLMClient)
    client._client = type("C", (), {"chat": type("Ch", (), {"completions": FakeCompletions()})()})()
    client._model, client._extra = "m", {}

    with pytest.raises(GroqRateLimitedError) as caught:
        client.complete(LLMRequest(prompt="hi"))

    assert isinstance(caught.value, (GroqClientError, LLMRateLimitedError))
    assert caught.value.retry_after_seconds == (pytest.approx(seconds) if seconds else None)


# ---- Post-call processing waits and tries again ----


class FlakyComplaints(ComplaintDetectionProvider):
    def __init__(self, failures: int, retry_after: float | None) -> None:
        self.failures = failures
        self.retry_after = retry_after
        self.calls = 0

    def detect(self, conversation, learning_context=()):
        self.calls += 1
        if self.calls <= self.failures:
            # As the providers raise it: wrapped by the client's own error.
            try:
                raise LLMRateLimitedError("limited", self.retry_after)
            except LLMRateLimitedError as exc:
                raise RuntimeError("Groq API call failed") from exc
        return [ComplaintDetectionResult("Cost", 0.9, "The bill was higher.")]


class Sentiment(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEGATIVE, 0.9, "Angry.")


class FlakySummary(SummaryGenerationProvider):
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0
        self._rules = RuleBasedSummaryProvider()

    def generate_summary(self, request):
        self.calls += 1
        if self.calls <= self.failures:
            raise LLMRateLimitedError("limited", 2.0)
        return self._rules.generate_summary(request)


def _completed_call(complaints, summary=None):
    waits: list[float] = []
    call_service = CallService(ConversationService(InMemoryConversationRepository()))
    call_service.start_call(CALL_ID)
    call_service.add_utterance(
        CALL_ID,
        Utterance(
            utterance_id="u1",
            transcript="The bill was much higher than you told me.",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=2.0,
        ),
    )
    call_service.end_call(CALL_ID, 10.0)
    workflow = CallWorkflowService(
        call_service,
        InMemoryConversationCoverageRepository(),
        ConversationAnalysisService(
            ComplaintAnalysisService(complaints), SentimentAnalysisService(Sentiment())
        ),
        NextQuestionService(RuleBasedQuestionProvider()),
        EstimationService(RuleBasedEstimationProvider(DEFAULT_PRICING_CONFIG)),
        PostCallSummaryService(summary or RuleBasedSummaryProvider()),
        sleep=waits.append,
    )
    return workflow, waits


def test_a_short_rate_limit_is_waited_out():
    complaints = FlakyComplaints(failures=1, retry_after=1.37)
    workflow, waits = _completed_call(complaints)

    summary = workflow.process_completed_call(CALL_ID)

    assert summary is not None
    assert complaints.calls == 2
    assert waits == [pytest.approx(2.37)]


def test_a_rate_limited_summary_is_tried_again():
    summary_provider = FlakySummary(failures=1)
    workflow, waits = _completed_call(FlakyComplaints(0, None), summary_provider)

    assert workflow.process_completed_call(CALL_ID) is not None
    assert summary_provider.calls == 2 and waits == [3.0]


def test_the_daily_limit_is_left_to_the_repair_job():
    complaints = FlakyComplaints(failures=1, retry_after=3600.0)
    workflow, waits = _completed_call(complaints)

    assert workflow.process_completed_call(CALL_ID) is None
    assert waits == []


def test_it_gives_up_after_three_attempts():
    complaints = FlakyComplaints(failures=5, retry_after=None)  # unknown wait: 20 s
    workflow, waits = _completed_call(complaints)

    assert workflow.process_completed_call(CALL_ID) is None
    assert complaints.calls == 3
    assert waits == [21.0, 21.0]
