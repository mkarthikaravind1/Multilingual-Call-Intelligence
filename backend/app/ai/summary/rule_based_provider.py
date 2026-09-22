from app.ai.summary.language_utils import DEFAULT_LANGUAGE, extract_languages
from app.ai.summary.provider import PostCallSummaryRequest, SummaryGenerationProvider
from app.domain.complaint_coverage import ComplaintCoverage, ComplaintCoverageStatus
from app.domain.post_call_summary import ComplaintSummary, PostCallSummary
from app.domain.utterance import Utterance
from app.domain.conversation import Conversation
# Coverage that was actually raised but not fully handled yet.
UNRESOLVED_STATUSES = frozenset(
    {
        ComplaintCoverageStatus.DETECTED,
        ComplaintCoverageStatus.PROBED,
        ComplaintCoverageStatus.UNRESOLVED,
    }
)


def _extract_languages(conversation: Conversation) -> tuple[str, ...]:
    languages: list[str] = []
    for utterance in conversation.utterances:
        for lang in utterance.languages:
            if lang not in languages:
                languages.append(lang)
    if not languages:
        languages.append(DEFAULT_LANGUAGE)
    return tuple(languages)


def _find_evidence(category: str, utterances: tuple[Utterance, ...]) -> str:
    keywords = [category.lower()] + [word.lower() for word in category.split()]
    for utterance in utterances:
        transcript_lower = utterance.transcript.lower()
        if any(keyword in transcript_lower for keyword in keywords):
            return utterance.transcript
    return f"No direct transcript evidence found for the '{category}' category."


def _build_complaint_summaries(
    complaint_coverages: tuple[ComplaintCoverage, ...],
    utterances: tuple[Utterance, ...],
) -> tuple[ComplaintSummary, ...]:
    summaries: list[ComplaintSummary] = []
    for coverage in complaint_coverages:
        if coverage.status == ComplaintCoverageStatus.NOT_RAISED:
            continue
        summaries.append(
            ComplaintSummary(
                category=coverage.category,
                description=(
                    f"{coverage.category} complaint identified during the call "
                    f"(status: {coverage.status.value})."
                ),
                status=coverage.status,
                evidence=_find_evidence(coverage.category, utterances),
                confidence=None,
            )
        )
    return tuple(summaries)


def _unresolved_issue_descriptions(complaints: tuple[ComplaintSummary, ...]) -> tuple[str, ...]:
    return tuple(c.description for c in complaints if c.status in UNRESOLVED_STATUSES)


def _build_overall_summary(call_id: str, complaints: tuple[ComplaintSummary, ...], sentiment_label: str) -> str:
    if not complaints:
        return f"Call {call_id}: no complaints were raised; overall customer sentiment was {sentiment_label}."
    categories = ", ".join(c.category for c in complaints)
    return (
        f"Call {call_id}: {len(complaints)} complaint(s) discussed ({categories}); "
        f"overall customer sentiment was {sentiment_label}."
    )


def _build_customer_summary(complaints: tuple[ComplaintSummary, ...], unresolved_issues: tuple[str, ...]) -> str:
    if not complaints:
        return "Thank you for calling. No issues were reported during this call."
    if not unresolved_issues:
        return "Thank you for calling. All reported issues were addressed during this call."
    return (
        f"Thank you for calling. {len(unresolved_issues)} of {len(complaints)} "
        "reported issue(s) remain unresolved and will be followed up."
    )


class RuleBasedSummaryProvider(SummaryGenerationProvider):
    """Deterministic, LLM-free SummaryGenerationProvider.

    Builds the PostCallSummary purely from the domain data already present
    on the request (conversation utterances + complaint coverages), so it
    is fully replaceable later by an LLM-backed provider without touching
    callers.
    """

    def generate_summary(self, request: PostCallSummaryRequest) -> PostCallSummary | None:
        utterances = request.conversation.utterances
        complaints = _build_complaint_summaries(request.complaint_coverages, utterances)
        unresolved_issues = _unresolved_issue_descriptions(complaints)
        languages = _extract_languages(request.conversation)

        return PostCallSummary(
            call_id=request.call_id,
            overall_summary=_build_overall_summary(
                request.call_id, complaints, request.sentiment.label.value.lower()
            ),
            languages=languages,
            sentiment=request.sentiment,
            complaints=complaints,
            unresolved_issues=unresolved_issues,
            actions_promised=(),
            follow_up_required=bool(unresolved_issues),
            customer_summary=_build_customer_summary(complaints, unresolved_issues),
            service_estimate=request.service_estimate,
        )