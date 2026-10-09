"""Accepted emerging complaint themes become complaint categories that
detection, next questions, summaries and feedback all recognise."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.ai.complaint.llm_provider import LLMComplaintProvider
from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.emerging_complaint.provider import (
    EmergingComplaintDiscoveryProvider,
    EmergingComplaintDiscoveryRequest,
)
from app.ai.emerging_complaint.rule_based_provider import (
    RuleBasedEmergingComplaintDiscoveryProvider,
)
from app.ai.llm.client import LLMClient, LLMRequest, LLMResponse
from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.ai.question.rule_based_provider import RuleBasedQuestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.conversation_coverage import ConversationCoverage
from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewError,
    EmergingComplaintReviewStatus,
)
from app.domain.utterance import SpeakerRole, Utterance
from app.domain.user import User, UserRole
from app.security.jwt import create_access_token
from app.services.complaint_category_catalog import ComplaintCategoryCatalog
from app.services.emerging_complaint_repository import InMemoryEmergingComplaintRepository
from app.services.next_question_service import NextQuestionService

ACCEPTED = EmergingComplaintReviewStatus.ACCEPTED
REJECTED = EmergingComplaintReviewStatus.REJECTED
PENDING = EmergingComplaintReviewStatus.PENDING_REVIEW


def candidate(candidate_id="emerging-1", proposed_name="The Wiper Makes A Squeaking Noise"):
    return EmergingComplaintCandidate(
        candidate_id=candidate_id,
        proposed_name=proposed_name,
        description="Customers say the wipers squeak after a service.",
        evidence=("the wiper squeaks",),
        occurrence_count=2,
        confidence=0.5,
        call_ids=("a", "b"),
    ).first_stored(1.0)


def accepted(name="Wiper Noise", description=None, **kwargs):
    return candidate(**kwargs).review(ACCEPTED, "sup@example.com", 2.0, None, name, description)


class FakeLLM(LLMClient):
    def __init__(self, reply: list[dict]) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompts.append(request.prompt)
        return LLMResponse(text=json.dumps(self.reply))


def conversation() -> Conversation:
    call = Conversation(call_id="call-1")
    call.add_utterance(
        Utterance(
            utterance_id="u1",
            transcript="The wipers squeak every time it rains",
            speaker_role=SpeakerRole.CUSTOMER,
            languages=("en",),
            start_time=0.0,
            end_time=1.0,
        )
    )
    return call


# ---- Accepting a theme ----


def test_accepting_names_the_category_and_reopening_keeps_the_name():
    theme = accepted("  Wiper   Noise ", " Squeaking wipers. ")
    assert (theme.category_name, theme.category_description) == ("Wiper Noise", "Squeaking wipers.")

    default = candidate(proposed_name="Ac Smell").review(ACCEPTED, "sup@example.com", 2.0)
    assert default.category_name == "Ac Smell"
    assert default.category_description == "Customers say the wipers squeak after a service."

    reopened = theme.review(PENDING, "sup@example.com", 3.0)
    assert reopened.category_name == "Wiper Noise"


@pytest.mark.parametrize("name", ["cost", "OTHER", "x" * 41])
def test_a_category_name_must_be_short_and_new(name):
    with pytest.raises(EmergingComplaintReviewError):
        accepted(name)


def test_a_long_proposed_name_needs_a_shorter_category_name():
    with pytest.raises(EmergingComplaintReviewError, match="at most 40"):
        candidate(proposed_name="Customers Keep Saying The Wipers Squeak After Service").review(
            ACCEPTED, "sup@example.com", 2.0
        )


# ---- The catalog ----


def test_catalog_lists_accepted_themes_between_the_built_ins_and_other():
    repository = InMemoryEmergingComplaintRepository()
    repository.save(accepted("Wiper Noise"))
    repository.save(accepted("Ac Smell", candidate_id="emerging-2"))
    repository.save(candidate(candidate_id="emerging-3"))  # pending: no category

    names = ComplaintCategoryCatalog(repository).names()

    assert names[-3:] == ("Ac Smell", "Wiper Noise", "Other")
    assert names[0] == "Cost" and len(names) == 12


def test_catalog_refreshes_after_the_cache_time():
    repository = InMemoryEmergingComplaintRepository()
    now = [0.0]
    catalog = ComplaintCategoryCatalog(repository, cache_seconds=30.0, clock=lambda: now[0])
    assert not catalog.custom()

    repository.save(accepted())
    assert not catalog.custom()  # still cached
    now[0] = 31.0
    assert [c.name for c in catalog.custom()] == ["Wiper Noise"]


def test_catalog_keeps_the_last_categories_when_the_repository_fails():
    repository = InMemoryEmergingComplaintRepository()
    repository.save(accepted())
    catalog = ComplaintCategoryCatalog(repository, cache_seconds=0.0)
    assert catalog.is_known("Wiper Noise")

    def broken(statuses):
        raise RuntimeError("database down")

    repository.list_by_status = broken  # type: ignore[method-assign]
    assert catalog.is_known("Wiper Noise")


# ---- Detection ----


def test_detection_is_told_about_accepted_themes_and_may_report_them():
    repository = InMemoryEmergingComplaintRepository()
    repository.save(accepted(description="Wipers squeak or judder."))
    llm = FakeLLM([{"category": "Wiper Noise", "confidence": 0.8, "evidence": "Wipers squeak."}])
    provider = LLMComplaintProvider(llm, ComplaintCategoryCatalog(repository))

    (result,) = provider.detect(conversation())

    assert result.category == "Wiper Noise"
    assert "- Wiper Noise: Wipers squeak or judder." in llm.prompts[0]
    assert llm.prompts[0].index("Wiper Noise") < llm.prompts[0].index("- Other")


def test_detection_rejects_categories_that_are_not_in_the_catalog():
    repository = InMemoryEmergingComplaintRepository()
    repository.save(accepted().review(REJECTED, "sup@example.com", 3.0))
    llm = FakeLLM([{"category": "Wiper Noise", "confidence": 0.8, "evidence": "Wipers squeak."}])

    assert LLMComplaintProvider(llm, ComplaintCategoryCatalog(repository)).detect(conversation()) == []
    assert "Wiper Noise" not in llm.prompts[0]


def test_records_keep_a_category_after_its_theme_is_rejected():
    coverage = ConversationCoverage(call_id="call-1")
    coverage.add("Wiper Noise").detect()
    assert coverage.get("Wiper Noise").status is ComplaintCoverageStatus.DETECTED
    with pytest.raises(ValueError):
        ComplaintCoverage(category=" ")


# ---- Next questions ----


class _RecordingQuestions(QuestionSuggestionProvider):
    def __init__(self) -> None:
        self.contexts: list[QuestionGenerationContext] = []

    def generate(self, context):
        self.contexts.append(context)
        return RuleBasedQuestionProvider().generate(context)


def test_next_question_follows_up_custom_categories_after_built_ins():
    coverage = ConversationCoverage(call_id="call-1")
    coverage.add("Wiper Noise").detect()
    questions = _RecordingQuestions()

    suggestion = NextQuestionService(questions).suggest_next_question(coverage)

    assert suggestion.target_category == "Wiper Noise"
    assert suggestion.question == "Could you tell me more about the issue you're facing?"

    coverage.add("Cost").detect()
    assert NextQuestionService(questions).suggest_next_question(coverage).target_category == "Cost"


def test_rule_based_questions_for_custom_categories_are_translated():
    suggestion = RuleBasedQuestionProvider().generate(
        QuestionGenerationContext(
            category="Wiper Noise",
            status=ComplaintCoverageStatus.PROBED,
            utterances=(),
            language="ta",
        )
    )
    assert suggestion.language == "ta" and suggestion.question_en
    assert suggestion.target_category == "Wiper Noise"


# ---- Discovery ----


class _RecordingDiscovery(EmergingComplaintDiscoveryProvider):
    def __init__(self) -> None:
        self.requests: list[EmergingComplaintDiscoveryRequest] = []

    def discover(self, request):
        self.requests.append(request)
        return ()


def test_rule_based_discovery_does_not_propose_an_accepted_category_again():
    def record(call_id):
        from app.ai.emerging_complaint.provider import CallComplaintRecord

        return CallComplaintRecord(
            call_id=call_id,
            utterances=(
                Utterance(
                    utterance_id=f"{call_id}-1",
                    transcript="Wiper noise",
                    speaker_role=SpeakerRole.CUSTOMER,
                    languages=("en",),
                    start_time=0.0,
                    end_time=1.0,
                ),
            ),
            complaint_coverages=(),
        )

    provider = RuleBasedEmergingComplaintDiscoveryProvider()
    records = (record("a"), record("b"))
    assert provider.discover(EmergingComplaintDiscoveryRequest(records))
    assert not provider.discover(
        EmergingComplaintDiscoveryRequest(records, known_categories=("Wiper Noise",))
    )


# ---- API ----


class _NoComplaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return []


class _Sentiment(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.6, "Calm.")


class _NoQuestions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


def _app(repository, discovery=None):
    services = build_api_services(
        _NoComplaints(),
        _Sentiment(),
        _NoQuestions(),
        Settings(_env_file=None, emerging_complaint_auto_discovery=False),  # type: ignore[call-arg]
        emerging_complaint_repository=repository,
        emerging_complaint_provider=discovery or _RecordingDiscovery(),
    )
    return create_app(services)


def _client(app, role: UserRole) -> TestClient:
    user = User(
        user_id=f"user-{role.value}",
        email=f"{role.value.lower()}@example.com",
        password_hash="unused",
        role=role,
        is_active=True,
        created_at=time.time(),
    )
    app.state.services.user_repository.save(user)
    return TestClient(app, headers={"Authorization": f"Bearer {create_access_token(user)}"})


def test_api_accepts_a_theme_as_a_named_category_and_lists_it():
    repository = InMemoryEmergingComplaintRepository()
    repository.save(candidate(proposed_name="Customers Keep Saying The Wipers Squeak After Service"))
    repository.save(candidate(candidate_id="emerging-2", proposed_name="Ac Smell"))
    app = _app(repository)
    icr = _client(app, UserRole.ICR)
    supervisor = _client(app, UserRole.SUPERVISOR)
    url = "/api/v1/emerging-complaints/emerging-1/review"

    too_long = supervisor.post(url, json={"decision": "accepted"})
    assert too_long.status_code == 409 and "at most 40" in too_long.json()["detail"]
    assert supervisor.post(url, json={"decision": "accepted", "category_name": "Cost"}).status_code == 409

    response = supervisor.post(
        url,
        json={
            "decision": "accepted",
            "category_name": "Wiper Noise",
            "category_description": "Wipers squeak or judder.",
        },
    )
    assert response.status_code == 200
    assert response.json()["category_name"] == "Wiper Noise"

    categories = icr.get("/api/v1/complaints/categories").json()
    assert [c["name"] for c in categories][-2:] == ["Wiper Noise", "Other"]
    assert categories[-2] == {
        "name": "Wiper Noise",
        "description": "Wipers squeak or judder.",
        "built_in": False,
        "candidate_id": "emerging-1",
    }

    clash = supervisor.post(
        "/api/v1/emerging-complaints/emerging-2/review",
        json={"decision": "accepted", "category_name": "wiper noise"},
    )
    assert clash.status_code == 409 and "Wiper Noise" in clash.json()["detail"]

    assert supervisor.post(url, json={"decision": "rejected"}).status_code == 200
    names = [c["name"] for c in icr.get("/api/v1/complaints/categories").json()]
    assert "Wiper Noise" not in names


def test_feedback_corrections_can_name_an_accepted_category():
    repository = InMemoryEmergingComplaintRepository()
    repository.save(accepted())
    app = _app(repository)
    learning = app.state.services.learning

    assert "Wiper Noise" in learning._complaint_categories()


def test_manual_discovery_tells_the_provider_about_accepted_categories():
    repository = InMemoryEmergingComplaintRepository()
    repository.save(accepted())
    discovery = _RecordingDiscovery()
    app = _app(repository, discovery)
    icr = _client(app, UserRole.ICR)
    for call_id in ("a", "b"):
        assert icr.post("/api/v1/calls", json={"call_id": call_id}).status_code == 201
        icr.post(
            f"/api/v1/calls/{call_id}/utterances",
            json={
                "utterance_id": f"{call_id}-0",
                "transcript": "The wipers squeak",
                "speaker_role": "CUSTOMER",
                "languages": ["en"],
                "start_time": 0.0,
                "end_time": 1.0,
            },
        )
        icr.post(f"/api/v1/calls/{call_id}/complete", json={"end_time": 9.0})

    app.state.services.emerging_complaint_service.discover()

    assert discovery.requests[0].known_categories == ("Wiper Noise",)
