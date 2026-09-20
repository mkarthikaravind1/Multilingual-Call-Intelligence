import logging

from pydantic import ValidationError

from app.api.v1.live_schemas import (
    LiveAnalysisEvent,
    LiveErrorCode,
    LiveErrorEvent,
    LiveEvent,
    LiveUtteranceMessage,
)
from app.api.v1.mappers import to_analysis_response, to_utterance
from app.services.call_service import CallService
from app.services.call_workflow_service import CallWorkflowService
from app.services.conversation_service import ConversationNotFoundError

logger = logging.getLogger(__name__)


class LiveCallHandler:
    def __init__(
        self,
        call_service: CallService,
        workflow_service: CallWorkflowService,
    ) -> None:
        self._call_service = call_service
        self._workflow_service = workflow_service

    def open(self, call_id: str) -> LiveErrorEvent | None:
        try:
            self._call_service.get_call(call_id)
        except ConversationNotFoundError as exc:
            return _error(call_id, LiveErrorCode.CALL_NOT_FOUND, str(exc))
        return None

    def handle(self, call_id: str, raw_message: str | None) -> LiveEvent:
        if raw_message is None:
            return _error(
                call_id,
                LiveErrorCode.INVALID_MESSAGE,
                "Only text messages containing JSON are supported.",
            )

        try:
            message = LiveUtteranceMessage.model_validate_json(raw_message)
        except ValidationError as exc:
            return _error(call_id, LiveErrorCode.INVALID_MESSAGE, _describe(exc))

        try:
            result = self._workflow_service.process_utterance(
                call_id, to_utterance(message)
            )
        except ConversationNotFoundError as exc:
            return _error(call_id, LiveErrorCode.CALL_NOT_FOUND, str(exc))
        except ValueError as exc:
            return _error(call_id, LiveErrorCode.INVALID_UTTERANCE, str(exc))
        except Exception:
            logger.exception("Live analysis failed for call %r", call_id)
            return _error(
                call_id,
                LiveErrorCode.INTERNAL_ERROR,
                "Analysis failed. Please try again.",
            )

        analysis = to_analysis_response(call_id, result)
        return LiveAnalysisEvent(
            utterance_id=message.utterance_id, **analysis.model_dump()
        )


def _error(call_id: str, code: LiveErrorCode, message: str) -> LiveErrorEvent:
    return LiveErrorEvent(code=code, call_id=call_id, message=message)


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'message'}: {error['msg']}"
        for error in exc.errors()
    )