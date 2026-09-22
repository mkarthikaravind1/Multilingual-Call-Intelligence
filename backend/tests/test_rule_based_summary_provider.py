import itertools
from decimal import Decimal

from app.ai.sentiment.provider import SentimentLabel, SentimentResult
from app.ai.summary.provider import PostCallSummaryRequest
from app.ai.summary.rule_based_provider import RuleBasedSummaryProvider
from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.conversation import Conversation
from app.domain.service_estimate import EstimatedPart, LabourEstimate, ServiceEstimate
from app.domain.utterance import SpeakerRole, Utterance

_utterance_ids = itertools.count(1)


def make_sentiment(label: SentimentLabel = SentimentLabel.NEUTRAL) -> SentimentResult:
    return SentimentResult(label, 0.6, "Customer was calm throughout.")


def make_utterance(
    transcript: str,
    languages: tuple[str, ...] = ("en",),
    role: SpeakerRole = SpeakerRole.CUSTOMER,
    start: float = 0.0,
    end: float = 1.0,
) -> Utterance:
    return Utterance(
        utterance_id=f"utt-{next(_utterance_ids)}",
        transcript=transcript,
        speaker_role=role,
        languages=languages,
        start_time=start,
        end_time=end,
    )


def make_conversation(call_id: str = "call-1", utterances: tuple[Utterance, ...] = ()) -> Conversation:
    conversation = Conversation(call_id=call_id)
    for utterance in utterances:
        conversation.add_utterance(utterance)
    return conversation


def make_coverage(category: str, status: ComplaintCoverageStatus) -> ComplaintCoverage:
    coverage = ComplaintCoverage(category)
    transitions = {
        ComplaintCoverageStatus.NOT_RAISED: [],
        ComplaintCoverageStatus.DETECTED: [coverage.detect],
        ComplaintCoverageStatus.PROBED: [coverage.detect, coverage.probe],
        ComplaintCoverageStatus.COVERED: [coverage.detect, coverage.probe, coverage.cover],
        ComplaintCoverageStatus.RESOLVED: [
            coverage.detect, coverage.probe, coverage.cover, coverage.resolve,
        ],
        ComplaintCoverageStatus.UNRESOLVED: [
            coverage.detect, coverage.probe, coverage.cover, coverage.mark_unresolved,
        ],
    }
    for step in transitions[status]:
        step()
    return coverage


def make_service_estimate() -> ServiceEstimate:
    return ServiceEstimate(
        service_name="Brake Pad Replacement",
        currency="INR",
        parts=(EstimatedPart("Brake Pad", 2, Decimal("500")),),
        labour=LabourEstimate(1.5, Decimal("400")),
        estimated_duration_hours=2.0,
    )


def make_request(
    call_id: str = "call-1",
    utterances: tuple[Utterance, ...] = (),
    complaint_coverages: tuple[ComplaintCoverage, ...] = (),
    sentiment: SentimentResult | None = None,
    service_estimate: ServiceEstimate | None = None,
) -> PostCallSummaryRequest:
    return PostCallSummaryRequest(
        call_id=call_id,
        conversation=make_conversation(call_id, utterances),
        complaint_coverages=complaint_coverages,
        sentiment=sentiment or make_sentiment(),
        service_estimate=service_estimate,
    )


# 1. Normal summary generation

def test_generates_valid_post_call_summary():
    request = make_request(
        utterances=(make_utterance("The turnaround time was too long.", languages=("en",)),),
        complaint_coverages=(make_coverage("Turnaround Time", ComplaintCoverageStatus.RESOLVED),),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.call_id == "call-1"
    assert summary.overall_summary
    assert summary.customer_summary


# 2. Language extraction

def test_derives_languages_from_utterances_in_first_seen_order():
    request = make_request(
        utterances=(
            make_utterance("Hello", languages=("en",)),
            make_utterance("Vanakkam", languages=("ta", "en")),
        ),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.languages == ("en", "ta")


def test_languages_fall_back_to_default_when_no_utterances():
    request = make_request(utterances=())
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.languages == ("en",)


# 3. Complaint extraction

def test_extracts_complaint_category_status_and_evidence():
    request = make_request(
        utterances=(make_utterance("The turnaround time was too long for my car.", languages=("en",)),),
        complaint_coverages=(make_coverage("Turnaround Time", ComplaintCoverageStatus.COVERED),),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert len(summary.complaints) == 1
    complaint = summary.complaints[0]
    assert complaint.category == "Turnaround Time"
    assert complaint.status == ComplaintCoverageStatus.COVERED
    assert "turnaround time" in complaint.evidence.lower()


def test_not_raised_categories_are_excluded_from_complaints():
    request = make_request(
        complaint_coverages=(make_coverage("Cost", ComplaintCoverageStatus.NOT_RAISED),),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.complaints == ()


def test_evidence_falls_back_when_no_matching_utterance():
    request = make_request(
        utterances=(make_utterance("Everything was fine.", languages=("en",)),),
        complaint_coverages=(make_coverage("Documentation", ComplaintCoverageStatus.DETECTED),),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert "no direct transcript evidence" in summary.complaints[0].evidence.lower()


# 4. Unresolved complaint handling

def test_unresolved_issues_include_detected_probed_and_unresolved_statuses():
    request = make_request(
        complaint_coverages=(
            make_coverage("Cost", ComplaintCoverageStatus.DETECTED),
            make_coverage("Hygiene", ComplaintCoverageStatus.PROBED),
            make_coverage("Staff Behaviour", ComplaintCoverageStatus.UNRESOLVED),
            make_coverage("Communication", ComplaintCoverageStatus.RESOLVED),
            make_coverage("Documentation", ComplaintCoverageStatus.COVERED),
        ),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert len(summary.unresolved_issues) == 3


def test_resolved_and_covered_complaints_are_not_unresolved():
    request = make_request(
        complaint_coverages=(
            make_coverage("Cost", ComplaintCoverageStatus.RESOLVED),
            make_coverage("Hygiene", ComplaintCoverageStatus.COVERED),
        ),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.unresolved_issues == ()


# 5. Follow-up flag

def test_follow_up_required_true_when_unresolved_issues_exist():
    request = make_request(
        complaint_coverages=(make_coverage("Cost", ComplaintCoverageStatus.DETECTED),),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.follow_up_required is True


def test_follow_up_required_false_when_no_unresolved_issues():
    request = make_request(
        complaint_coverages=(make_coverage("Cost", ComplaintCoverageStatus.RESOLVED),),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.follow_up_required is False


# 6. Service estimate preservation

def test_preserves_service_estimate_from_request():
    estimate = make_service_estimate()
    request = make_request(service_estimate=estimate)
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.service_estimate is estimate


def test_service_estimate_none_is_preserved_as_none():
    request = make_request(service_estimate=None)
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.service_estimate is None


# 7. Empty / minimal conversation

def test_handles_empty_conversation_and_no_complaints():
    request = make_request(utterances=(), complaint_coverages=())
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert summary.complaints == ()
    assert summary.unresolved_issues == ()
    assert summary.follow_up_required is False
    assert summary.languages == ("en",)


# 8. Multiple complaints

def test_handles_multiple_complaints_with_mixed_statuses():
    request = make_request(
        utterances=(
            make_utterance("The cost was too high.", languages=("en",)),
            make_utterance("The workshop was not clean.", languages=("en",)),
        ),
        complaint_coverages=(
            make_coverage("Cost", ComplaintCoverageStatus.RESOLVED),
            make_coverage("Hygiene", ComplaintCoverageStatus.DETECTED),
            make_coverage("Parts Availability", ComplaintCoverageStatus.NOT_RAISED),
        ),
    )
    provider = RuleBasedSummaryProvider()

    summary = provider.generate_summary(request)

    assert summary is not None
    assert len(summary.complaints) == 2
    assert {c.category for c in summary.complaints} == {"Cost", "Hygiene"}
    assert len(summary.unresolved_issues) == 1
    assert summary.follow_up_required is True