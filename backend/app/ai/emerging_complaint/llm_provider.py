import hashlib
import json
import logging
import re
from typing import Any

from app.ai.emerging_complaint.provider import (
    EmergingComplaintDiscoveryProvider,
    EmergingComplaintDiscoveryRequest,
)
from app.ai.llm.client import LLMClient, LLMRequest
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.emerging_complaint_candidate import EmergingComplaintCandidate
from app.domain.utterance import SpeakerRole

logger = logging.getLogger(__name__)

_MIN_DISTINCT_CALLS = 2
_REQUIRED_CANDIDATE_FIELDS = ("proposed_name", "description", "evidence", "confidence")
_REQUIRED_EVIDENCE_FIELDS = ("call_id", "quote")

_NORMALIZED_CATEGORIES = frozenset(c.casefold() for c in COMPLAINT_CATEGORIES)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")

_RESPONSE_SHAPE = (
    '[{"proposed_name": "<short new category name>", '
    '"description": "<1-2 sentence description of the pattern>", '
    '"evidence": [{"call_id": "<call id>", "quote": "<short customer quote>"}], '
    '"confidence": <number between 0.0 and 1.0>}]'
)


def _normalize(text: str) -> str:
    lowered = text.casefold()
    stripped = _NON_ALNUM_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def _stable_candidate_id(proposed_name: str) -> str:
    digest = hashlib.sha256(_normalize(proposed_name).encode("utf-8")).hexdigest()[:12]
    return f"emerging-llm-{digest}"


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()


class LLMEmergingComplaintDiscoveryProvider(EmergingComplaintDiscoveryProvider):
    """Groups customer utterances by semantic similarity via the LLM, so
    differently-worded complaints about the same issue can be linked -
    unlike the rule-based provider's exact-text matching. No embeddings;
    the LLM does the clustering in a single prompt.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def discover(
        self, request: EmergingComplaintDiscoveryRequest
    ) -> tuple[EmergingComplaintCandidate, ...]:
        transcripts_by_call = self._customer_transcripts_by_call(request)
        if len(transcripts_by_call) < _MIN_DISTINCT_CALLS:
            return ()

        response = self._llm_client.complete(self._build_request(transcripts_by_call))
        return self._parse_response(response.text, valid_call_ids=set(transcripts_by_call))

    @staticmethod
    def _customer_transcripts_by_call(
        request: EmergingComplaintDiscoveryRequest,
    ) -> dict[str, list[str]]:
        transcripts_by_call: dict[str, list[str]] = {}
        for record in request.call_records:
            customer_lines = [
                u.transcript.strip()
                for u in record.utterances
                if u.speaker_role == SpeakerRole.CUSTOMER
            ]
            if customer_lines:
                transcripts_by_call[record.call_id] = customer_lines
        return transcripts_by_call

    def _build_request(self, transcripts_by_call: dict[str, list[str]]) -> LLMRequest:
        calls_block = "\n\n".join(
            f"Call {call_id}:\n" + "\n".join(f"- {line}" for line in lines)
            for call_id, lines in transcripts_by_call.items()
        )
        categories = "\n".join(f"- {c}" for c in COMPLAINT_CATEGORIES)
        prompt = (
            "You analyse customer utterances from several automotive service calls "
            "and look for recurring complaint patterns - the same underlying issue, "
            "even if customers describe it in different words.\n\n"
            f"Known complaint categories (do NOT propose any of these, or close "
            f"variants of them):\n{categories}\n\n"
            f"Customer utterances by call:\n{calls_block}\n\n"
            "Rules:\n"
            "- Only propose a pattern that is genuinely supported by the text; do not invent one.\n"
            "- Only propose a pattern with evidence from at least 2 different calls.\n"
            "- Do not propose anything matching a known category above.\n"
            "- evidence quotes must be taken from the customer utterances above.\n\n"
            "Respond with ONLY a JSON array and nothing else "
            "(no markdown, no commentary), in exactly this shape:\n"
            f"{_RESPONSE_SHAPE}\n"
            "confidence must be a number between 0.0 and 1.0, not text.\n"
            "If there are no such recurring patterns, respond with exactly: []"
        )
        return LLMRequest(prompt=prompt)

    def _parse_response(
        self, text: str, valid_call_ids: set[str]
    ) -> tuple[EmergingComplaintCandidate, ...]:
        if not isinstance(text, str):
            return self._reject("response text is not a string")
        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError:
            return self._reject("response is not valid JSON")

        if not isinstance(data, list):
            return self._reject("JSON response is not a list")

        try:
            parsed = [self._parse_item(item) for item in data]
        except (TypeError, ValueError) as exc:
            return self._reject(str(exc))

        candidates = []
        for proposed_name, description, evidence, confidence in parsed:
            candidate = self._build_candidate(
                proposed_name, description, evidence, confidence, valid_call_ids
            )
            if candidate is not None:
                candidates.append(candidate)
        return tuple(candidates)

    @staticmethod
    def _parse_item(item: Any) -> tuple[str, str, list[dict], float]:
        if not isinstance(item, dict):
            raise TypeError("each item must be an object")

        missing = [f for f in _REQUIRED_CANDIDATE_FIELDS if f not in item]
        if missing:
            raise ValueError(f"missing fields: {missing}")

        proposed_name = item["proposed_name"]
        description = item["description"]
        evidence = item["evidence"]
        confidence = item["confidence"]

        if not isinstance(proposed_name, str) or not proposed_name.strip():
            raise TypeError("proposed_name must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise TypeError("description must be a non-empty string")
        if not isinstance(evidence, list) or not evidence:
            raise TypeError("evidence must be a non-empty list")

        for entry in evidence:
            if not isinstance(entry, dict):
                raise TypeError("each evidence entry must be an object")
            missing_evidence = [f for f in _REQUIRED_EVIDENCE_FIELDS if f not in entry]
            if missing_evidence:
                raise ValueError(f"evidence entry missing fields: {missing_evidence}")
            if not isinstance(entry["call_id"], str) or not entry["call_id"].strip():
                raise TypeError("evidence call_id must be a non-empty string")
            if not isinstance(entry["quote"], str) or not entry["quote"].strip():
                raise TypeError("evidence quote must be a non-empty string")

        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise TypeError("confidence must be a number")
        if not (0.0 <= confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")

        return proposed_name.strip(), description.strip(), evidence, float(confidence)

    def _build_candidate(
        self,
        proposed_name: str,
        description: str,
        evidence: list[dict],
        confidence: float,
        valid_call_ids: set[str],
    ) -> EmergingComplaintCandidate | None:
        if _normalize(proposed_name) in _NORMALIZED_CATEGORIES:
            logger.info("Skipping candidate matching an existing category: %s", proposed_name)
            return None

        known_evidence = [e for e in evidence if e["call_id"] in valid_call_ids]
        distinct_calls = {e["call_id"] for e in known_evidence}
        if len(distinct_calls) < _MIN_DISTINCT_CALLS:
            logger.info(
                "Skipping candidate with evidence from fewer than %d calls: %s",
                _MIN_DISTINCT_CALLS,
                proposed_name,
            )
            return None

        try:
            return EmergingComplaintCandidate(
                candidate_id=_stable_candidate_id(proposed_name),
                proposed_name=proposed_name,
                description=description,
                evidence=tuple(e["quote"] for e in known_evidence),
                occurrence_count=len(known_evidence),
                confidence=confidence,
            )
        except (TypeError, ValueError) as exc:
            logger.info("Skipping invalid candidate %s: %s", proposed_name, exc)
            return None

    @staticmethod
    def _reject(reason: str) -> tuple[EmergingComplaintCandidate, ...]:
        logger.warning("Discarding invalid LLM emerging-complaint response: %s", reason)
        return ()