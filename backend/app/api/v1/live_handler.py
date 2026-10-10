import logging
from collections.abc import Callable

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
        category_names: Callable[[str], str] | None = None,
    ) -> None:
        self._call_service = call_service
        self._workflow_service = workflow_service
        # A complaint category's stored name -> the one it has now.
        self._category_names = category_names

    def open(self, call_id: str) -> LiveErrorEvent | None:
        try:
            self._call_service.get_call(call_id)
        except ConversationNotFoundError as exc:
            return _error(call_id, LiveErrorCode.CALL_NOT_FOUND, str(exc))
        return None

    def revision(self, call_id: str) -> str | None:
        return self._workflow_service.live_revision(call_id)

    def snapshot(self, call_id: str) -> LiveEvent:
        """The call's current analysis, pushed when it changed elsewhere
        (e.g. speech from the telephony stream). Never runs the AI providers."""
        try:
            conversation = self._call_service.get_call(call_id)
            result = self._workflow_service.analyze_call(call_id)
        except ConversationNotFoundError as exc:
            return _error(call_id, LiveErrorCode.CALL_NOT_FOUND, str(exc))
        except Exception:
            logger.exception("Reading the live analysis failed for call %r", call_id)
            return _error(
                call_id,
                LiveErrorCode.INTERNAL_ERROR,
                "Could not refresh the analysis.",
            )
        latest = conversation.latest_utterance
        analysis = to_analysis_response(call_id, result, self._category_names)
        return LiveAnalysisEvent(
            utterance_id="" if latest is None else latest.utterance_id,
            **analysis.model_dump(),
        )

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

        analysis = to_analysis_response(call_id, result, self._category_names)
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