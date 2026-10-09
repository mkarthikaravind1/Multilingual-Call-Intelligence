"""One LLM request for a live call's complaints, sentiment and escalation.

During a call these were three requests, each sending the whole transcript
again. Here the transcript is sent once, followed by each task's own
instructions (built by its provider, so they match its separate request),
and the answer is checked section by section with each provider's own
checks. A section that is missing or unusable comes back as None, and the
caller asks that provider on its own instead: a bad combined answer costs
an extra request, never a result.
"""

import json
import logging
from dataclasses import dataclass

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.complaint.provider import ComplaintDetectionResult
from app.ai.escalation.llm_provider import LLMEscalationProvider
from app.ai.escalation.provider import EscalationContext
from app.ai.llm.client import LLMClient, LLMRequest
from app.ai.sentiment.llm_provider import LLMSentimentProvider
from app.ai.sentiment.provider import SentimentResult
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.escalation import EscalationSignal
from app.domain.runtime_improvement_context import RuntimeImprovementContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveAnalysis:
    """Each section, or None when it has to be asked for separately."""

    complaints: list[ComplaintDetectionResult] | None
    sentiment: SentimentResult | None
    # None as well when no LLM escalation detector is configured.
    escalation_signals: tuple[EscalationSignal, ...] | None


class LLMLiveAnalysisProvider:
    def __init__(
        self,
        llm_client: LLMClient,
        complaints: LLMComplaintProvider,
        sentiment: LLMSentimentProvider,
        escalation: LLMEscalationProvider | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._complaints = complaints
        self._sentiment = sentiment
        self._escalation = escalation

    def analyze(
        self,
        conversation: Conversation,
        complaint_guidance: tuple[RuntimeImprovementContext, ...] = (),
        sentiment_guidance: tuple[RuntimeImprovementContext, ...] = (),
    ) -> LiveAnalysis:
        complaint_task, allowed = self._complaints.task_instructions(complaint_guidance)
        try:
            response = self._llm_client.complete(
                self._build_request(conversation, complaint_task, sentiment_guidance)
            )
            data = json.loads(_strip_code_fence(response.text or ""))
            if not isinstance(data, dict):
                raise ValueError("the answer is not a JSON object")
        except Exception as exc:
            logger.warning(
                "Combined live analysis failed for call %r (%s); asking each part separately",
                conversation.call_id,
                exc,
            )
            return LiveAnalysis(None, None, None)

        escalation = None
        if self._escalation is not None:
            # The rules (run by the escalation service) use the analysis
            # results; the quote check needs only the conversation.
            context = EscalationContext(
                conversation, ConversationCoverage(call_id=conversation.call_id), None
            )
            escalation = self._escalation.parse_signals(data.get("escalation"), context)
        return LiveAnalysis(
            complaints=self._complaints.parse_items(data.get("complaints"), allowed),
            sentiment=self._sentiment.parse_object(data.get("sentiment")),
            escalation_signals=escalation,
        )

    def _build_request(
        self,
        conversation: Conversation,
        complaint_task: str,
        sentiment_guidance: tuple[RuntimeImprovementContext, ...],
    ) -> LLMRequest:
        transcript = "\n".join(
            f"{u.speaker_role.value}: {u.transcript.strip()}" for u in conversation.utterances
        )
        keys = '"complaints", "sentiment"'
        escalation_task = ""
        if self._escalation is not None:
            keys += ', "escalation"'
            escalation_task = (
                "TASK 3 - escalation. Flag signs that the call is escalating and needs a "
                "supervisor.\n\n"
                f"{self._escalation.task_instructions()}\n\n"
            )
        prompt = (
            "You analyse a transcript of a live automotive service call between an ICR "
            "(customer service representative) and a customer. The conversation may be "
            "in Tamil, Telugu, Kannada, Malayalam, English or a mix. Do each task below "
            "on the same conversation, following that task's own rules.\n\n"
            f"Conversation:\n{transcript}\n\n"
            "TASK 1 - complaints. Identify the complaints the customer has raised.\n\n"
            f"{complaint_task}\n\n"
            "TASK 2 - sentiment. Determine the overall sentiment of the conversation.\n\n"
            f"{self._sentiment.task_instructions(sentiment_guidance)}\n\n"
            f"{escalation_task}"
            f"Respond with ONLY one JSON object with the keys {keys} (each answer in the "
            "shape given in its task) and nothing else (no markdown, no commentary). "
            "Every confidence must be a number between 0.0 and 1.0, not text."
        )
        return LLMRequest(prompt=prompt)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()
