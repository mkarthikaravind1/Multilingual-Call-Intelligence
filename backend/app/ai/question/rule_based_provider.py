from app.ai.question.provider import QuestionGenerationContext, QuestionSuggestionProvider
from app.core.constants import COMPLAINT_CATEGORIES
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource

_DETECTED_QUESTIONS = {
    "Cost": "Could you tell me which specific charge or amount seemed incorrect?",
    "Hygiene": "Could you describe the hygiene issue you noticed?",
    "Hospitality": "Could you tell me more about how you were treated at the service center?",
    "Service Quality": "Could you describe what wasn't satisfactory about the service?",
    "Turnaround Time": "Could you tell me the expected completion time you were given?",
    "Communication": "Could you tell me what information you feel wasn't communicated to you?",
    "Parts Availability": "Could you tell me which part was unavailable or delayed?",
    "Staff Behaviour": "Could you describe the behaviour of the staff member involved?",
    "Documentation": "Could you tell me which document or paperwork had an issue?",
    "Other": "Could you tell me more about the issue you're facing?",
}

_PROBED_QUESTIONS = {
    "Cost": "Was the amount charged different from what was originally quoted?",
    "Hygiene": "Was this a one-time observation or has it happened on previous visits?",
    "Hospitality": "Did this happen with a specific staff member or throughout your visit?",
    "Service Quality": "Which specific part of the service fell short of your expectations?",
    "Turnaround Time": "By how long was the actual completion delayed from what was promised?",
    "Communication": "At which stage of the process did the communication gap occur?",
    "Parts Availability": "Were you given an alternative or an updated timeline for the part?",
    "Staff Behaviour": "Can you describe exactly what was said or done that concerned you?",
    "Documentation": "Was the document missing, incorrect, or delayed?",
    "Other": "Can you give a specific example of what went wrong?",
}


class RuleBasedQuestionProvider(QuestionSuggestionProvider):
    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        if context.category not in COMPLAINT_CATEGORIES:
            raise ValueError(f"Unsupported complaint category: {context.category!r}.")

        if context.status == ComplaintCoverageStatus.DETECTED:
            question = _DETECTED_QUESTIONS[context.category]
            priority, confidence = 2, 0.6
        elif context.status == ComplaintCoverageStatus.PROBED:
            question = _PROBED_QUESTIONS[context.category]
            priority, confidence = 1, 0.75
        else:
            return None

        return QuestionSuggestion(
            question=question,
            target_category=context.category,
            priority=priority,
            reason=f"'{context.category}' is {context.status.value} and needs follow-up.",
            source=SuggestionSource.RULE_BASED,
            confidence=confidence,
        )