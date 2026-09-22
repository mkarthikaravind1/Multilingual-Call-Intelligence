import json
import logging

from app.ai.llm.client import LLMClient, LLMRequest
from app.ai.summary.language_utils import extract_languages
from app.ai.summary.provider import PostCallSummaryRequest, SummaryGenerationProvider
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.post_call_summary import ComplaintSummary, PostCallSummary

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = (
    "overall_summary",
    "complaints",
    "unresolved_issues",
    "actions_promised",
    "follow_up_required",
    "customer_summary",
)


def _parse_status(value: object) -> ComplaintCoverageStatus | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    for status in ComplaintCoverageStatus:
        if status.name.lower() == normalized:
            return status
    return None


def _as_str_list(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


class LLMPostCallSummaryProvider(SummaryGenerationProvider):
    """SummaryGenerationProvider backed by an LLMClient.

    The model is only trusted to produce the narrative fields
    (overall_summary, complaints, unresolved_issues, actions_promised,
    follow_up_required, customer_summary). call_id, languages, sentiment
    and service_estimate always come from the request, never the model.
    Every field pulled from the completion is type-checked here and then
    re-validated by PostCallSummary/ComplaintSummary's own __post_init__;
    on any parsing or validation failure this returns None instead of
    raising, so a bad completion degrades gracefully rather than breaking
    call analysis.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def generate_summary(self, request: PostCallSummaryRequest) -> PostCallSummary | None:
        prompt = self._build_prompt(request)

        try:
            response = self._llm_client.complete(LLMRequest(prompt=prompt))
        except Exception:
            logger.exception(
                "LLM completion failed while generating summary for call %s", request.call_id
            )
            return None

        payload = self._parse_json(response.text, request.call_id)
        if payload is None:
            return None

        return self._build_summary(request, payload)

    def _build_prompt(self, request: PostCallSummaryRequest) -> str:
        transcript = "\n".join(
            f"[{utterance.speaker_role.value}] {utterance.transcript}"
            for utterance in request.conversation.utterances
        )
        detected = ", ".join(
            f"{coverage.category} ({coverage.status.name.lower()})"
            for coverage in request.complaint_coverages
            if coverage.status != ComplaintCoverageStatus.NOT_RAISED
        ) or "none"
        allowed_categories = ", ".join(sorted(COMPLAINT_CATEGORIES))
        allowed_statuses = ", ".join(status.name.lower() for status in ComplaintCoverageStatus)

        return (
            "You are summarizing a customer service call transcript.\n"
            f"Call ID: {request.call_id}\n"
            f"Detected complaint categories: {detected}\n"
            f"Overall sentiment: {request.sentiment.label.value}\n"
            "Transcript:\n"
            f"{transcript}\n\n"
            "Respond with ONLY a single JSON object (no markdown, no commentary) "
            "with exactly these keys:\n"
            '- "overall_summary": string\n'
            '- "complaints": array of objects, each with "category" '
            f"(one of: {allowed_categories}), \"description\" (string), "
            f'"status" (one of: {allowed_statuses}), "evidence" (string), '
            'and optional "confidence" (number 0-1)\n'
            '- "unresolved_issues": array of strings\n'
            '- "actions_promised": array of strings\n'
            '- "follow_up_required": boolean\n'
            '- "customer_summary": string\n'
        )

    def _parse_json(self, text: str, call_id: str) -> dict | None:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLM summary response for call %s was not valid JSON", call_id)
            return None

        if not isinstance(payload, dict):
            logger.warning("LLM summary response for call %s was not a JSON object", call_id)
            return None

        missing = [key for key in _REQUIRED_KEYS if key not in payload]
        if missing:
            logger.warning(
                "LLM summary response for call %s is missing keys: %s", call_id, missing
            )
            return None

        return payload

    def _parse_complaints(
        self, raw_complaints: object, call_id: str
    ) -> tuple[ComplaintSummary, ...] | None:
        if not isinstance(raw_complaints, list):
            logger.warning("LLM summary 'complaints' for call %s was not a list", call_id)
            return None

        complaints: list[ComplaintSummary] = []
        for entry in raw_complaints:
            if not isinstance(entry, dict):
                logger.warning("LLM summary complaint entry for call %s was not an object", call_id)
                return None

            status = _parse_status(entry.get("status"))
            confidence = entry.get("confidence")
            if (
                status is None
                or not isinstance(entry.get("category"), str)
                or not isinstance(entry.get("description"), str)
                or not isinstance(entry.get("evidence"), str)
            ):
                logger.warning("LLM summary complaint entry for call %s is malformed", call_id)
                return None

            if confidence is not None and (
                isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            ):
                logger.warning("LLM summary confidence for call %s is not numeric", call_id)
                return None

            try:
                complaints.append(
                    ComplaintSummary(
                        category=entry["category"],
                        description=entry["description"],
                        status=status,
                        evidence=entry["evidence"],
                        confidence=confidence,
                    )
                )
            except (TypeError, ValueError):
                logger.exception(
                    "LLM summary complaint entry for call %s failed validation", call_id
                )
                return None

        return tuple(complaints)

    def _build_summary(
        self, request: PostCallSummaryRequest, payload: dict
    ) -> PostCallSummary | None:
        complaints = self._parse_complaints(payload["complaints"], request.call_id)
        if complaints is None:
            return None

        unresolved_issues = _as_str_list(payload["unresolved_issues"])
        actions_promised = _as_str_list(payload["actions_promised"])

        if (
            unresolved_issues is None
            or actions_promised is None
            or not isinstance(payload["overall_summary"], str)
            or not isinstance(payload["customer_summary"], str)
            or not isinstance(payload["follow_up_required"], bool)
        ):
            logger.warning(
                "LLM summary response for call %s had a malformed field type", request.call_id
            )
            return None

        try:
            return PostCallSummary(
                call_id=request.call_id,
                overall_summary=payload["overall_summary"],
                languages=extract_languages(request.conversation),
                sentiment=request.sentiment,
                complaints=complaints,
                unresolved_issues=tuple(unresolved_issues),
                actions_promised=tuple(actions_promised),
                follow_up_required=payload["follow_up_required"],
                customer_summary=payload["customer_summary"],
                service_estimate=request.service_estimate,
            )
        except (TypeError, ValueError):
            logger.exception(
                "LLM summary response for call %s failed PostCallSummary validation",
                request.call_id,
            )
            return None