from enum import Enum
from typing import Literal

from pydantic import BaseModel

from app.api.v1.schemas import CallAnalysisResponse, UtteranceRequest


class LiveErrorCode(str, Enum):
    INVALID_MESSAGE = "invalid_message"
    INVALID_UTTERANCE = "invalid_utterance"
    CALL_NOT_FOUND = "call_not_found"
    INTERNAL_ERROR = "internal_error"


class LiveUtteranceMessage(UtteranceRequest):
    type: Literal["utterance"]


class LiveAnalysisEvent(CallAnalysisResponse):
    type: Literal["analysis"] = "analysis"
    utterance_id: str


class LiveErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: LiveErrorCode
    call_id: str
    message: str


LiveEvent = LiveAnalysisEvent | LiveErrorEvent