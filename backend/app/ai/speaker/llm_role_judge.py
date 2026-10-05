"""Asks an LLM which of a live call's speakers is the ICR, when what they
said so far gives the phrase rules (ContentRoleScorer) too little to go on."""

import json
import logging
import re
from collections.abc import Sequence

from app.ai.llm.client import LLMClient, LLMRequest

logger = logging.getLogger(__name__)

_MAX_LINES = 12
_MAX_LINE_CHARS = 300
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class LLMRoleJudge:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def icr_speaker(self, lines: Sequence[tuple[str, str]]) -> str | None:
        """lines: (speaker_id, what they said), in call order. Returns the
        speaker_id of the ICR, or None when the LLM cannot tell."""
        speakers = {speaker for speaker, _ in lines}
        if len(speakers) < 2:
            return None
        transcript = "\n".join(
            f"{speaker}: {text.strip()[:_MAX_LINE_CHARS]}" for speaker, text in lines[-_MAX_LINES:]
        )
        prompt = (
            "This is the start of a phone call between an automotive service centre's ICR "
            "(customer service representative) and a customer; either of them may have "
            "placed the call. "
            "It may be in Tamil, Telugu, Kannada, Malayalam, English or a mix. The "
            "speakers are labelled by voice only.\n\n"
            f"{transcript}\n\n"
            "Which speaker is the ICR? The ICR introduces themselves from the service "
            "centre, greets, offers help or asks for feedback, asks for details such as "
            "the vehicle or registration number, and promises action; the "
            "customer talks about their own vehicle or problem. If the lines do not make it "
            'clear, answer null. Reply with JSON only: {"icr": "<speaker label or null>", '
            '"confidence": <0 to 1>}'
        )
        try:
            response = self._llm_client.complete(LLMRequest(prompt=prompt))
            match = _JSON_OBJECT.search(response.text or "")
            payload = json.loads(match.group(0)) if match else {}
        except Exception:
            logger.warning("The LLM could not judge the speaker roles.", exc_info=True)
            return None
        if not isinstance(payload, dict):
            return None
        icr = payload.get("icr")
        try:
            confidence = float(payload.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        if icr in speakers and confidence >= 0.7:
            return icr
        return None
