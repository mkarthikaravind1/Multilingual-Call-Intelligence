"""The Complaints page's cards and the Covered stage: a covered detection
moves a complaint to Covered, and each complaint comes with its call's
number, start, ICR and the customer's own lines."""

import json
import time
from types import SimpleNamespace
from typing import cast

from fastapi.testclient import TestClient

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.complaint.provider import ComplaintDetectionProvider, ComplaintDetectionResult
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentResult
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.sentiment import SentimentLabel
from app.domain.user import User, UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.security.jwt import create_access_token
from app.services.complaint_analysis_service import ComplaintAnalysisService
from app.services.in_memory_conversation_repository import InMemoryConversationRepository

# ---- The detector reports "covered" ----


class _OneAnswer(LLMClient):
    def __init__(self, answer: list[dict]) -> None:
        self._text = json.dumps(answer)
        self.prompt = ""

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompt = request.prompt
        return LLMResponse(text=self._text)


def _one_line_call() -> Conversation:
    utterance = Utterance(
        utterance_id="1",
        transcript="The bill was more than the estimate.",
        speaker_role=SpeakerRole.CUSTOMER,
        languages=("en",),
        start_time=0.0,
        end_time=1.0,
    )
    return cast(Conversation, SimpleNamespace(utterances=(utterance,)))


def _item(**extra) -> dict:
    return {"category": "Cost", "confidence": 0.9, "evidence": "Bill too high.", **extra}


def test_the_detector_is_asked_for_covered_and_reads_it():
    client = _OneAnswer([_item(probed=True, covered=True)])
    (result,) = LLMComplaintProvider(client).detect(_one_line_call())
    assert result.probed and result.covered
    assert '"covered": <true or false>' in client.prompt
    assert "told the customer what will be done" in client.prompt


def test_covered_is_false_when_missing_or_not_true():
    for extra in ({}, {"covered": "no"}, {"covered": None}):
        (result,) = LLMComplaintProvider(_OneAnswer([_item(**extra)])).detect(_one_line_call())
        assert not result.covered


def test_a_category_reported_twice_is_covered_if_either_says_so():
    client = _OneAnswer([_item(covered=True), _item(confidence=0.95)])
    (result,) = LLMComplaintProvider(client).detect(_one_line_call())
    assert result.covered and result.confidence == 0.95


def test_the_combined_live_task_asks_for_covered_too():
    task, _ = LLMComplaintProvider(_OneAnswer([])).task_instructions()
    assert '"covered": <true or false>' in task


# ---- Coverage moves to Covered ----


def _status_after(*detections: ComplaintDetectionResult) -> ComplaintCoverageStatus:
    service = ComplaintAnalysisService(cast(ComplaintDetectionProvider, None))
    conversation = Conversation(call_id="c")
    coverage = ConversationCoverage(call_id="c")
    for detection in detections:
        coverage = service.apply(conversation, coverage, [detection])
    complaint = coverage.get("Cost")
    assert complaint is not None
    return complaint.status


def _cost(probed: bool = False, covered: bool = False) -> ComplaintDetectionResult:
    return ComplaintDetectionResult("Cost", 0.9, "Bill too high.", probed=probed, covered=covered)


def test_a_covered_detection_moves_the_complaint_to_covered():
    # At once from not raised, or from detected or probed.
    assert _status_after(_cost(covered=True)) is ComplaintCoverageStatus.COVERED
    assert _status_after(_cost(), _cost(covered=True)) is ComplaintCoverageStatus.COVERED
    assert (
        _status_after(_cost(probed=True), _cost(probed=True, covered=True))
        is ComplaintCoverageStatus.COVERED
    )


def test_covered_never_goes_back():
    assert (
        _status_after(_cost(covered=True), _cost(), _cost(probed=True))
        is ComplaintCoverageStatus.COVERED
    )
    assert _status_after(_cost(probed=True)) is ComplaintCoverageStatus.PROBED


# ---- The API: call details and the customer's lines ----


class _Detector(ComplaintDetectionProvider):
    """Cost from the customer's lines about money; the ICR's line names it
    too, but only the customer's words belong on the card. name_lines=False:
    a detector that does not say which lines (as on older calls)."""

    def __init__(self, name_lines: bool = True) -> None:
        self._name_lines = name_lines

    def detect(self, conversation, learning_context=()):
        lines = tuple(
            number
            for number, utterance in enumerate(conversation.utterances, start=1)
            if "bill" in utterance.transcript.lower()
        )
        if not lines:
            return []
        return [
            ComplaintDetectionResult(
                "Cost", 0.9, "Bill too high.", lines=lines if self._name_lines else ()
            )
        ]


class _Sentiment(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.6, "Calm.")


class _Questions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _app(name_lines: bool = True):
    services = build_api_services(
        _Detector(name_lines),
        _Sentiment(),
        _Questions(),
        Settings(_env_file=None, emerging_complaint_auto_discovery=False),  # type: ignore[call-arg]
    )
    return create_app(services)


def _signed_in(app, role: UserRole, name: str | None = None) -> tuple[TestClient, User]:
    user = User(
        user_id=f"user-{role.value}",
        email=f"{role.value.lower()}@example.com",
        password_hash="unused",
        role=role,
        is_active=True,
        created_at=time.time(),
        display_name=name,
    )
    app.state.services.user_repository.save(user)
    client = TestClient(app, headers={"Authorization": f"Bearer {create_access_token(user)}"})
    return client, user


def _say(client: TestClient, call_id: str, index: int, text: str, role: str) -> None:
    response = client.post(
        f"/api/v1/calls/{call_id}/utterances",
        json={
            "utterance_id": f"{call_id}-{index}",
            "transcript": text,
            "speaker_role": role,
            "languages": ["en"],
            "start_time": 1000.0 + index,
            "end_time": 1001.0 + index,
        },
    )
    assert response.status_code == 200


def test_each_complaint_carries_its_call_icr_and_the_customers_words():
    app = _app()
    # The ICR who starts the call is the call's ICR.
    icr, _ = _signed_in(app, UserRole.ICR, name="Priya")
    started = icr.post("/api/v1/calls", json={"call_id": "CALL-7", "start_time": 1000.0})
    assert started.status_code == 201
    _say(icr, "CALL-7", 0, "The bill was 4000 more than the estimate.", "CUSTOMER")
    _say(icr, "CALL-7", 1, "Let me check the bill for you.", "ICR")
    _say(icr, "CALL-7", 2, "And the bill had a charge I never agreed to.", "CUSTOMER")

    (item,) = icr.get("/api/v1/complaints").json()
    assert item["call_id"] == "CALL-7"
    assert item["icr_name"] == "Priya"
    assert item["call_started_at"] == 1000.0
    assert item["customer_lines"] == [
        "The bill was 4000 more than the estimate.",
        "And the bill had a charge I never agreed to.",
    ]

    # The same details on one complaint, after a status change, and on the call page.
    assert icr.get("/api/v1/complaints/CALL-7:Cost").json()["icr_name"] == "Priya"
    saved = icr.post("/api/v1/complaints/CALL-7:Cost/status", json={"status": "unresolved"})
    assert saved.json()["customer_lines"] == item["customer_lines"]
    (on_call,) = icr.get("/api/v1/calls/CALL-7/complaints").json()["complaints"]
    assert on_call["icr_name"] == "Priya"


def test_a_call_without_a_start_or_tagged_lines_still_lists_its_complaint():
    app = _app(name_lines=False)
    icr, _ = _signed_in(app, UserRole.ICR)
    assert icr.post("/api/v1/calls", json={"call_id": "CALL-8"}).status_code == 201
    _say(icr, "CALL-8", 0, "My bill is wrong.", "CUSTOMER")

    (item,) = icr.get("/api/v1/complaints").json()
    # No display name: the ICR's email; start time 0 means not recorded.
    assert item["icr_name"] == "icr@example.com"
    assert item["call_started_at"] is None
    assert item["customer_lines"] == []


# ---- Reading several calls at once ----


def test_get_many_returns_only_calls_that_exist():
    repository = InMemoryConversationRepository()
    repository.add(Conversation(call_id="a"))
    repository.add(Conversation(call_id="b"))
    found = repository.get_many(["a", "missing", "a", "b"])
    assert sorted(found) == ["a", "b"]
    assert repository.get_many([]) == {}
