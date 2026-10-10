import json
import logging
from typing import Any

from app.ai.learning_guidance import format_learning_guidance
from app.ai.llm.client import LLMClient, LLMRequest
from app.ai.sentiment.provider import (
    SentimentAnalysisProvider,
    SentimentLabel,
    SentimentResult,
    UtteranceSentiment,
)
from app.domain.conversation import Conversation
from app.domain.utterance import SpeakerRole, Utterance
from app.domain.runtime_improvement_context import RuntimeImprovementContext

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("label", "confidence", "evidence")

_NO_CONTENT_EVIDENCE = "No conversation content is available to determine sentiment."
_UNDETERMINED_EVIDENCE = "Sentiment could not be determined from the model response."

_GUARDRAILS = (
    "Analyse only the conversation provided; do not invent facts.",
    "Determine the customer's overall sentiment across the whole conversation.",
    "Do not let a single positive or negative sentence decide the label when the "
    "complete conversation suggests otherwise.",
    "Use exactly one label: POSITIVE, NEUTRAL, NEGATIVE, FRUSTRATED or ESCALATING.",
    "NEGATIVE: the customer is unhappy or dissatisfied. FRUSTRATED: the customer is "
    "annoyed or fed up (repeating themselves, losing patience). ESCALATING: the "
    "customer's anger is rising (threats, demands for a manager or a refund, legal or "
    "public complaints, refusing to go on). Choose the strongest that clearly applies.",
    "evidence must be one concise sentence explaining the sentiment using only "
    "information present in the conversation; it must not contain invented information.",
)

_LABELS = "POSITIVE | NEUTRAL | NEGATIVE | FRUSTRATED | ESCALATING"
_RESPONSE_SHAPE = (
    f'{{"label": "<{_LABELS}>", '
    '"confidence": <number between 0.0 and 1.0>, '
    '"evidence": "<short evidence from the conversation>"}'
)
# With lines to rate, the same object carries their tones too.
_LINES_SHAPE = (
    f'"lines": [{{"line": <line number>, "label": "<{_LABELS}>", '
    '"confidence": <number between 0.0 and 1.0>}, ...]'
)
# Lines rated in one request; a longer backlog (a whole call rated after
# it ended) keeps its most recent ones.
MAX_LINES_PER_REQUEST = 40
# The ICR's lines are not rated: the tone that matters is the customer's.
_RATED_ROLES = frozenset({SpeakerRole.CUSTOMER, SpeakerRole.UNKNOWN})


def lines_to_rate(conversation: Conversation) -> dict[int, Utterance]:
    """The customer's lines that have no tone yet, by their number in the
    conversation (1 is its first line)."""
    unrated = [
        (number, utterance)
        for number, utterance in enumerate(conversation.utterances, start=1)
        if utterance.sentiment is None and utterance.speaker_role in _RATED_ROLES
    ]
    return dict(unrated[-MAX_LINES_PER_REQUEST:])


def transcript_for(conversation: Conversation, lines: dict[int, Utterance]) -> str:
    """The conversation as the prompt shows it. With lines to rate, every
    line carries its number, so they are named without being sent twice."""
    if not lines:
        return "\n".join(
            f"{u.speaker_role.value}: {u.transcript.strip()}" for u in conversation.utterances
        )
    return "\n".join(
        f"[{number}] {u.speaker_role.value}: {u.transcript.strip()}"
        for number, u in enumerate(conversation.utterances, start=1)
    )


def _lines_task(lines: dict[int, Utterance]) -> str:
    if not lines:
        return ""
    numbers = ", ".join(str(number) for number in lines)
    return (
        "Also rate the customer's tone on each of these numbered lines of the "
        f"conversation: {numbers}. Give one label per line, judged from that line in "
        "its context.\n\n"
    )


def _response_shape(lines: dict[int, Utterance]) -> str:
    if not lines:
        return _RESPONSE_SHAPE
    return f"{_RESPONSE_SHAPE[:-1]}, {_LINES_SHAPE}}}"


class LLMSentimentProvider(SentimentAnalysisProvider):
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def analyze(
        self,
        conversation: Conversation,
        learning_context: tuple[RuntimeImprovementContext, ...] = (),
    ) -> SentimentResult:
        if not conversation.utterances:
            return SentimentResult(SentimentLabel.NEUTRAL, 0.0, _NO_CONTENT_EVIDENCE)
        response = self._llm_client.complete(
            self._build_request(conversation, learning_context)
        )
        return self._parse_response(response.text, conversation)

    def _build_request(
        self,
        conversation: Conversation,
        learning_context: tuple[RuntimeImprovementContext, ...] = (),
    ) -> LLMRequest:
        rules = "\n".join(f"- {rule}" for rule in _GUARDRAILS)
        lines = lines_to_rate(conversation)
        prompt = (
            "You analyse a transcript of an automotive service call between an ICR "
            "(customer service representative) and a customer, and determine the "
            "overall sentiment of the conversation.\n\n"
            f"Conversation:\n{transcript_for(conversation, lines)}\n\n"
            f"Rules:\n{rules}\n\n"
            f"{format_learning_guidance(learning_context)}"
            f"{_lines_task(lines)}"
            "Respond with ONLY a single JSON object and nothing else "
            "(no markdown, no commentary), in exactly this shape:\n"
            f"{_response_shape(lines)}\n"
            "confidence must be a number between 0.0 and 1.0, not text."
        )
        return LLMRequest(prompt=prompt)

    def _parse_response(
        self, text: str, conversation: Conversation | None = None
    ) -> SentimentResult:
        if not isinstance(text, str):
            return self._reject("response text is not a string")
        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError:
            return self._reject("response is not valid JSON")

        result = self.parse_object(data, conversation)
        return result if result is not None else self._reject_quietly()

    def task_instructions(
        self,
        learning_context: tuple[RuntimeImprovementContext, ...] = (),
        conversation: Conversation | None = None,
    ) -> str:
        """This provider's task inside a combined live-analysis request (see
        LLMLiveAnalysisProvider): the same rules and guidance as analyze()'s
        own prompt. With the conversation, its unrated customer lines are
        rated too."""
        rules = "\n".join(f"- {rule}" for rule in _GUARDRAILS)
        lines = {} if conversation is None else lines_to_rate(conversation)
        return (
            f"Rules:\n{rules}\n\n"
            f"{format_learning_guidance(learning_context)}"
            f"{_lines_task(lines)}"
            f'"sentiment" is a JSON object in exactly this shape:\n{_response_shape(lines)}'
        )

    def parse_object(
        self, data: Any, conversation: Conversation | None = None
    ) -> SentimentResult | None:
        """The sentiment in a decoded answer, checked as analyze() checks it;
        None when the answer is unusable. conversation: the one the answer
        is about, when its lines were to be rated."""
        if not isinstance(data, dict):
            self._reject("JSON response is not an object")
            return None
        try:
            result = self._build_result(data)
        except (TypeError, ValueError) as exc:
            self._reject(str(exc))
            return None
        if conversation is None:
            return result
        return SentimentResult(
            result.label,
            result.confidence,
            result.evidence,
            _line_tones(data.get("lines"), lines_to_rate(conversation)),
        )

    @staticmethod
    def _reject_quietly() -> SentimentResult:
        # parse_object() has already logged why.
        return SentimentResult(SentimentLabel.NEUTRAL, 0.0, _UNDETERMINED_EVIDENCE)

    @staticmethod
    def _build_result(data: dict[str, Any]) -> SentimentResult:
        missing = [f for f in _REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(f"missing fields: {missing}")

        evidence = data["evidence"]
        if not isinstance(evidence, str):
            raise TypeError("evidence must be a string")

        return SentimentResult(
            label=SentimentLabel(data["label"]),
            confidence=data["confidence"],
            evidence=evidence.strip(),
        )

    @staticmethod
    def _reject(reason: str) -> SentimentResult:
        logger.warning("Discarding invalid LLM sentiment response: %s", reason)
        return SentimentResult(SentimentLabel.NEUTRAL, 0.0, _UNDETERMINED_EVIDENCE)


def _line_tones(items: Any, asked: dict[int, Utterance]) -> tuple[UtteranceSentiment, ...]:
    """The usable line tones in an answer. Line tones are extra: a missing
    or malformed one is left out (that line is asked about again later),
    and never spoils the overall sentiment."""
    if not asked or not isinstance(items, list):
        return ()
    tones: dict[int, UtteranceSentiment] = {}
    for item in items:
        try:
            number = item["line"]
            if isinstance(number, bool) or not isinstance(number, int):
                number = int(str(number).strip())
            utterance = asked[number]
            tones[number] = UtteranceSentiment(
                utterance_id=utterance.utterance_id,
                label=SentimentLabel(str(item["label"]).strip().upper()),
                confidence=item["confidence"],
                transcript=utterance.transcript,
            )
        except (KeyError, TypeError, ValueError):
            continue
    if len(tones) < len(asked):
        logger.info("The model rated %d of the %d lines it was asked about", len(tones), len(asked))
    return tuple(tones.values())


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()