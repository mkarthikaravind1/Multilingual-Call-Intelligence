"""What reaches a reviewer in the AI Improvement Center: complaint themes
that are new and widespread, and the corrections people made (not the AI's
own outputs)."""

from app.ai.emerging_complaint.provider import (
    CallComplaintRecord,
    EmergingComplaintDiscoveryRequest,
)
from app.ai.emerging_complaint.rule_based_provider import (
    RuleBasedEmergingComplaintDiscoveryProvider,
)
from app.domain.emerging_complaint_candidate import (
    EmergingComplaintCandidate,
    EmergingComplaintReviewStatus,
)
from app.domain.sentiment import SentimentLabel
from app.domain.user import UserRole
from app.domain.utterance import SpeakerRole, Utterance
from app.services.emerging_complaint_repository import InMemoryEmergingComplaintRepository
from tests.test_emerging_complaint_categories import _app, _client
from tests.test_learning_api import BASE, _call_with_utterance, _correct, loop  # noqa: F401

PENDING = EmergingComplaintReviewStatus.PENDING_REVIEW
REJECTED = EmergingComplaintReviewStatus.REJECTED


# ---- The search: known complaints and small talk are not themes ----


def _line(call_id: str, text: str, tone=None, categories=()) -> CallComplaintRecord:
    return CallComplaintRecord(
        call_id=call_id,
        utterances=(
            Utterance(
                utterance_id=f"{call_id}-1",
                transcript=text,
                speaker_role=SpeakerRole.CUSTOMER,
                languages=("en",),
                start_time=0.0,
                end_time=3.0,
                sentiment=tone,
                complaint_categories=tuple(categories),
            ),
        ),
        complaint_coverages=(),
    )


def _themes(*records: CallComplaintRecord) -> list[str]:
    found = RuleBasedEmergingComplaintDiscoveryProvider().discover(
        EmergingComplaintDiscoveryRequest(call_records=records)
    )
    return [candidate.proposed_name for candidate in found]


def test_a_wording_the_ai_filed_under_a_category_on_any_call_is_not_a_theme():
    bill = "The bill was much more than I was told."

    # Filed under Cost on one call only; the others were never annotated.
    assert _themes(_line("a", bill), _line("b", bill, categories=("Cost",)), _line("c", bill)) == []
    # Under a category an administrator or a reviewer added, too.
    assert _themes(_line("a", bill), _line("b", bill, categories=("Hidden Charges",))) == []


def test_a_wording_filed_under_other_is_what_a_theme_is_made_of():
    wipers = "The wipers squeak since the service."

    assert _themes(
        _line("a", wipers, tone=SentimentLabel.NEUTRAL, categories=("Other",)),
        _line("b", wipers, tone=SentimentLabel.NEUTRAL, categories=("Other",)),
    ) == ["The Wipers Squeak Since The Service"]


def test_small_talk_the_ai_never_found_unhappy_is_not_a_theme():
    greeting = "Hi, I am calling about my Maruti Swift."

    assert _themes(
        _line("a", greeting, tone=SentimentLabel.NEUTRAL),
        _line("b", greeting, tone=SentimentLabel.POSITIVE),
        _line("c", greeting),
    ) == []


def test_an_unhappy_wording_without_a_category_is_a_theme():
    smell = "There is a burning smell from the vents."

    assert _themes(
        _line("a", smell, tone=SentimentLabel.NEUTRAL),
        _line("b", smell, tone=SentimentLabel.FRUSTRATED),
    ) == ["There Is A Burning Smell From The Vents"]


def test_a_wording_the_ai_never_rated_is_kept_as_before():
    smell = "There is a burning smell from the vents."

    assert _themes(_line("a", smell), _line("b", smell)) == ["There Is A Burning Smell From The Vents"]


def test_a_theme_has_a_short_name_a_plain_description_and_each_wording_once():
    long = (
        "And one more thing, I was told the repair would cost around 8000 rupees "
        "and nobody asked me before adding extra work."
    )
    (theme,) = RuleBasedEmergingComplaintDiscoveryProvider().discover(
        EmergingComplaintDiscoveryRequest(
            call_records=(_line("a", long), _line("b", long), _line("c", long.upper()))
        )
    )

    # Short enough to be accepted as a category name as it stands.
    assert theme.proposed_name == "And One More Thing I Was Told The…"
    assert len(theme.proposed_name) <= 40
    assert theme.description == "Customers said this, in the same words, on 3 separate calls."
    assert theme.evidence == (long, long.upper())
    assert (theme.occurrence_count, theme.call_ids) == (3, ("a", "b", "c"))


# ---- The list: weak themes are held back ----


def _stored(candidate_id: str, calls: int, seen_at: float, status=PENDING) -> EmergingComplaintCandidate:
    candidate = EmergingComplaintCandidate(
        candidate_id=candidate_id,
        proposed_name=f"Theme {candidate_id}",
        description="Customers said this.",
        evidence=("a quote",),
        occurrence_count=calls,
        confidence=0.5,
        call_ids=tuple(f"call-{n}" for n in range(calls)),
    ).first_stored(seen_at)
    if status is not PENDING:
        candidate = candidate.review(status, "sup@example.com", seen_at)
    return candidate


def _listing(*candidates: EmergingComplaintCandidate):
    repository = InMemoryEmergingComplaintRepository()
    for candidate in candidates:
        repository.save(candidate)
    app = _app(repository)
    return _client(app, UserRole.SUPERVISOR), repository


def _ids(client, **params) -> list[str]:
    body = client.get("/api/v1/emerging-complaints", params=params).json()
    return [c["candidate_id"] for c in body["candidates"]]


def test_a_theme_waits_until_it_has_come_up_on_three_calls():
    client, _ = _listing(_stored("wide", 5, 10.0), _stored("three", 3, 10.0), _stored("two", 2, 10.0))

    body = client.get("/api/v1/emerging-complaints").json()

    assert [c["candidate_id"] for c in body["candidates"]] == ["wide", "three"]
    assert body["hidden_pending"] == 1
    assert _ids(client, status="pending_review") == ["wide", "three"]


def test_a_theme_the_search_no_longer_finds_is_held_back():
    # "old" was last found by an earlier run; the latest run found "new".
    client, _ = _listing(_stored("old", 9, 10.0), _stored("new", 4, 20.0))

    body = client.get("/api/v1/emerging-complaints").json()

    assert [c["candidate_id"] for c in body["candidates"]] == ["new"]
    assert body["hidden_pending"] == 1


def test_a_held_back_theme_returns_when_it_is_found_again():
    client, repository = _listing(_stored("old", 9, 10.0), _stored("new", 4, 20.0))

    repository.save(repository.get("old").refreshed_from(repository.get("old"), 20.0))

    assert _ids(client) == ["old", "new"]


def test_a_theme_someone_decided_on_always_shows():
    client, _ = _listing(
        _stored("rejected-small", 2, 10.0, status=REJECTED), _stored("new", 4, 20.0)
    )

    assert _ids(client) == ["new", "rejected-small"]
    assert _ids(client, status="rejected") == ["rejected-small"]
    assert client.get("/api/v1/emerging-complaints").json()["hidden_pending"] == 0


def test_with_no_themes_nothing_is_hidden():
    client, _ = _listing()

    body = client.get("/api/v1/emerging-complaints").json()

    assert (body["candidates"], body["hidden_pending"]) == ([], 0)


# ---- Corrections: what people judged, without the AI's own outputs ----


def test_corrections_lists_what_people_corrected_and_counts_the_rest(loop):  # noqa: F811
    _call_with_utterance(loop.icr, "call-a")
    _call_with_utterance(loop.icr, "call-b")
    assert loop.icr.get(f"{BASE}/corrections").json()["corrections"] == []

    assert _correct(loop.icr, "call-a").status_code == 201

    body = loop.supervisor.get(f"{BASE}/corrections").json()
    (correction,) = body["corrections"]
    assert (correction["call_id"], correction["evidence_type"]) == ("call-a", "human_correction")
    assert (correction["actual_value"], correction["human_correction"]) == (
        "Turnaround Time",
        "Communication",
    )
    # The AI's outputs on both calls are counted, not listed.
    everything = loop.icr.get(f"{BASE}/evidence").json()
    assert body["evidence_total"] == len(everything) > 1


def test_corrections_are_newest_first(loop):  # noqa: F811
    for call_id in ("call-a", "call-b", "call-c"):
        _call_with_utterance(loop.icr, call_id)
        assert _correct(loop.icr, call_id).status_code == 201

    corrections = loop.icr.get(f"{BASE}/corrections").json()["corrections"]

    assert [c["call_id"] for c in corrections] == ["call-c", "call-b", "call-a"]


def test_corrections_need_a_signed_in_member_of_staff(loop):  # noqa: F811
    from fastapi.testclient import TestClient

    assert TestClient(loop.icr.app).get(f"{BASE}/corrections").status_code == 401
