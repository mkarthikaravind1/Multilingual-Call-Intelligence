"""Each suggested question is checked against what the customer already
said; one asking for that is replaced once, else nothing is suggested."""

import json

from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.llm_provider import LLMQuestionProvider
from app.ai.question.provider import QuestionGenerationContext
from app.ai.question.rule_based_provider import RuleBasedQuestionProvider
from app.composition.providers import create_question_provider
from app.core.config import Settings
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.utterance import SpeakerRole, Utterance

ASKED_AGAIN = "When was the previous AC repair performed?"
NEW = "Which part is not in stock?"


class ScriptedLLM(LLMClient):
    """Suggests the questions in turn; answers each check from `answered`."""

    def __init__(self, questions, answered, check_reply=None) -> None:
        self.questions = list(questions)
        self.answered = answered
        self.check_reply = check_reply
        self.prompts: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompts.append(request.prompt)
        if "Has the customer already given" in request.prompt:
            if self.check_reply is not None:
                return LLMResponse(text=self.check_reply)
            question = request.prompt.split("Suggested question: ", 1)[1].split("\n", 1)[0]
            yes = question in self.answered
            return LLMResponse(
                text=json.dumps({"already_answered": yes, "where": "on the 1st of September" if yes else ""})
            )
        return LLMResponse(
            text=json.dumps(
                {
                    "question": self.questions.pop(0),
                    "target_category": "Service Quality",
                    "priority": 1,
                    "reason": "Needed.",
                    "confidence": 0.9,
                }
            )
        )


def _context() -> QuestionGenerationContext:
    return QuestionGenerationContext(
        category="Service Quality",
        status=ComplaintCoverageStatus.DETECTED,
        utterances=(
            Utterance(
                utterance_id="u1",
                transcript="I brought it in on the 1st of September for the same AC problem.",
                speaker_role=SpeakerRole.CUSTOMER,
                languages=("en",),
                start_time=0.0,
                end_time=3.0,
            ),
        ),
    )


def _questions(llm):
    return [p for p in llm.prompts if "Has the customer already given" not in p]


def test_a_new_question_is_kept_after_one_check():
    llm = ScriptedLLM([NEW], answered=set())

    suggestion = LLMQuestionProvider(llm, check_answered=True).generate(_context())

    assert suggestion.question == NEW
    assert len(llm.prompts) == 2


def test_a_question_already_answered_is_replaced_once():
    llm = ScriptedLLM([ASKED_AGAIN, NEW], answered={ASKED_AGAIN})

    suggestion = LLMQuestionProvider(llm, check_answered=True).generate(_context())

    assert suggestion.question == NEW
    second_request = _questions(llm)[1]
    assert f"the customer has already given what they ask for: {ASKED_AGAIN}" in second_request


def test_nothing_is_suggested_when_the_second_try_is_answered_too():
    other = "What date did you bring the car in?"
    llm = ScriptedLLM([ASKED_AGAIN, other], answered={ASKED_AGAIN, other})

    provider = LLMQuestionProvider(llm, fallback=RuleBasedQuestionProvider(), check_answered=True)

    # Not the generic fallback either: an empty panel beats a redundant question.
    assert provider.generate(_context()) is None
    assert len(_questions(llm)) == 2


def test_a_failed_check_keeps_the_suggestion():
    llm = ScriptedLLM([NEW], answered=set(), check_reply="not json")

    suggestion = LLMQuestionProvider(llm, check_answered=True).generate(_context())

    assert suggestion.question == NEW


def test_without_the_check_there_is_one_request():
    llm = ScriptedLLM([ASKED_AGAIN], answered={ASKED_AGAIN})

    suggestion = LLMQuestionProvider(llm).generate(_context())

    assert suggestion.question == ASKED_AGAIN
    assert len(llm.prompts) == 1


def test_the_setting_turns_the_check_on_and_off():
    for enabled in (True, False):
        llm = ScriptedLLM([NEW], answered=set())
        settings = Settings(_env_file=None, question_answered_check=enabled)  # type: ignore[call-arg]

        create_question_provider(llm, settings).generate(_context())

        assert len(llm.prompts) == (2 if enabled else 1)
