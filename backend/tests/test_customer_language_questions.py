import json

import pytest

from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.llm_provider import LLMQuestionProvider
from app.ai.question.provider import QuestionGenerationContext
from app.ai.question.rule_based_provider import RuleBasedQuestionProvider
from app.ai.question.translations import DETECTED_QUESTIONS, PROBED_QUESTIONS
from app.core.constants import COMPLAINT_CATEGORIES
from app.core.languages import is_written_in_script
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.customer_language import customer_language
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource
from app.domain.utterance import SpeakerRole, Utterance
from app.services.live_analysis_store import LiveAnalysisSnapshot, _deserialize, _serialize
from app.services.next_question_service import NextQuestionService

TAMIL_QUESTION = "சொன்ன நேரத்தை விட வேலை எவ்வளவு தாமதமாக முடிந்தது?"


def _utterance(role: SpeakerRole, *languages: str, start: float = 0.0) -> Utterance:
    return Utterance(
        utterance_id=f"u-{start}",
        transcript="text",
        speaker_role=role,
        languages=languages,
        start_time=start,
        end_time=start + 1,
    )


class FakeLLMClient(LLMClient):
    def __init__(self, response: dict | str | Exception) -> None:
        self.response = response
        self.request: LLMRequest | None = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.request = request
        if isinstance(self.response, Exception):
            raise self.response
        text = self.response if isinstance(self.response, str) else json.dumps(self.response)
        return LLMResponse(text=text)


def _context(language: str = "ta") -> QuestionGenerationContext:
    return QuestionGenerationContext(
        category="Turnaround Time",
        status=ComplaintCoverageStatus.PROBED,
        utterances=(),
        language=language,
    )


def _llm_answer(**overrides) -> dict:
    answer = {
        "question": TAMIL_QUESTION,
        "question_en": "How long was the work delayed?",
        "target_category": "Turnaround Time",
        "priority": 1,
        "reason": "delay not yet measured",
        "confidence": 0.8,
    }
    answer.update(overrides)
    return answer


# --- The customer's language ---


def test_customer_language_is_the_customers_main_indian_language():
    utterances = (
        _utterance(SpeakerRole.ICR, "te", start=0),
        _utterance(SpeakerRole.CUSTOMER, "ta", "en", start=1),
        _utterance(SpeakerRole.CUSTOMER, "en", start=2),
        _utterance(SpeakerRole.CUSTOMER, "ta", start=3),
    )
    assert customer_language(utterances) == "ta"


def test_customer_speaking_only_english_gets_english_even_if_the_icr_does_not():
    utterances = (
        _utterance(SpeakerRole.ICR, "ta", start=0),
        _utterance(SpeakerRole.CUSTOMER, "en", start=1),
    )
    assert customer_language(utterances) == "en"


def test_unknown_speakers_count_until_the_customer_is_known():
    assert customer_language((_utterance(SpeakerRole.UNKNOWN, "ml"),)) == "ml"
    assert customer_language((_utterance(SpeakerRole.ICR, "kn"),)) == "kn"
    assert customer_language(()) == "en"


def test_next_question_service_passes_the_customer_language():
    received: list[QuestionGenerationContext] = []

    class Provider(RuleBasedQuestionProvider):
        def generate(self, context):
            received.append(context)
            return super().generate(context)

    coverage = ConversationCoverage(call_id="call-1")
    coverage.add("Cost").detect()

    suggestion = NextQuestionService(Provider()).suggest_next_question(
        coverage, (_utterance(SpeakerRole.CUSTOMER, "ml"),)
    )

    assert received[0].language == "ml"
    assert suggestion is not None and suggestion.language == "ml"


# --- Rule-based questions ---


@pytest.mark.parametrize("language", ["ta", "te", "kn", "ml"])
def test_every_rule_based_question_is_translated_in_its_script(language):
    for questions in (DETECTED_QUESTIONS, PROBED_QUESTIONS):
        assert set(questions[language]) == set(COMPLAINT_CATEGORIES)
        for question in questions[language].values():
            assert is_written_in_script(question, language)


def test_rule_based_question_is_in_the_customer_language_with_english():
    suggestion = RuleBasedQuestionProvider().generate(_context("te"))

    assert suggestion is not None
    assert suggestion.language == "te"
    assert suggestion.question == PROBED_QUESTIONS["te"]["Turnaround Time"]
    assert suggestion.question_en == (
        "By how long was the actual completion delayed from what was promised?"
    )


def test_rule_based_question_in_english_has_no_english_line():
    suggestion = RuleBasedQuestionProvider().generate(_context("en"))

    assert suggestion is not None
    assert suggestion.language == "en"
    assert suggestion.question_en is None


# --- LLM questions ---


def test_llm_is_asked_for_the_question_in_the_customer_script():
    client = FakeLLMClient(_llm_answer())

    suggestion = LLMQuestionProvider(client).generate(_context("ta"))

    assert client.request is not None
    assert "in Tamil script" in client.request.prompt
    assert '"question_en"' in client.request.prompt
    assert suggestion is not None
    assert suggestion.question == TAMIL_QUESTION
    assert suggestion.question_en == "How long was the work delayed?"
    assert suggestion.language == "ta"


def test_llm_english_prompt_is_unchanged_in_shape():
    answer = _llm_answer(question="How long was the delay?")
    del answer["question_en"]
    client = FakeLLMClient(answer)

    suggestion = LLMQuestionProvider(client).generate(_context("en"))

    assert client.request is not None and '"question_en"' not in client.request.prompt
    assert suggestion is not None
    assert (suggestion.language, suggestion.question_en) == ("en", None)


@pytest.mark.parametrize(
    "answer",
    [
        _llm_answer(question="How long was the work delayed?"),  # Tamil in English
        _llm_answer(question="Velai evvalavu late aachu?"),  # Tanglish, Latin letters
        {k: v for k, v in _llm_answer().items() if k != "question_en"},
        "not json",
    ],
)
def test_unusable_llm_answer_falls_back_to_the_rule_based_question(answer):
    provider = LLMQuestionProvider(FakeLLMClient(answer), fallback=RuleBasedQuestionProvider())

    suggestion = provider.generate(_context("ta"))

    assert suggestion is not None
    assert suggestion.source == SuggestionSource.RULE_BASED
    assert suggestion.question == PROBED_QUESTIONS["ta"]["Turnaround Time"]


def test_llm_failure_falls_back_to_the_rule_based_question():
    provider = LLMQuestionProvider(
        FakeLLMClient(RuntimeError("rate limited")), fallback=RuleBasedQuestionProvider()
    )

    suggestion = provider.generate(_context("kn"))

    assert suggestion is not None and suggestion.language == "kn"


def test_llm_saying_nothing_to_ask_is_not_replaced():
    provider = LLMQuestionProvider(FakeLLMClient("null"), fallback=RuleBasedQuestionProvider())

    assert provider.generate(_context("ta")) is None


def test_without_a_fallback_unusable_answers_give_no_suggestion():
    provider = LLMQuestionProvider(FakeLLMClient(_llm_answer(question="English text")))

    assert provider.generate(_context("ta")) is None


# --- Stored and served ---


def test_live_analysis_keeps_the_question_language():
    suggestion = QuestionSuggestion(
        question=TAMIL_QUESTION,
        target_category="Turnaround Time",
        priority=1,
        reason="r",
        source=SuggestionSource.LLM,
        language="ta",
        question_en="How long was the work delayed?",
    )
    snapshot = LiveAnalysisSnapshot(
        sentiment=None, question_suggestion=suggestion, service_estimate=None
    )

    restored = _deserialize(_serialize(snapshot)).question_suggestion

    assert restored == suggestion


def test_suggestion_rejects_an_unsupported_language():
    with pytest.raises(ValueError):
        QuestionSuggestion(
            question="q",
            target_category="Cost",
            priority=1,
            reason="r",
            source=SuggestionSource.LLM,
            language="hi",
        )
