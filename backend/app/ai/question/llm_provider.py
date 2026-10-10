import json
import logging
import re
from dataclasses import replace
from typing import Any

from app.ai.learning_guidance import format_learning_guidance
from app.ai.llm.client import LLMClient, LLMRequest
from app.ai.llm.json_answer import UnusableAnswer, decode_json
from app.ai.question.provider import (
    OpenComplaint,
    QuestionGenerationContext,
    QuestionSuggestionProvider,
)
from app.core.languages import ENGLISH, is_written_in_script, language_name
from app.domain.question_suggestion import QuestionSuggestion, SuggestionSource

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("question", "target_category", "priority", "reason")

_NO_CONVERSATION = "(no conversation available yet)"

# Asking about one given complaint (the rule-based order's choice).
_ONE_CATEGORY_RULES = (
    "The question must directly address the target complaint category.",
    "Do not ask about any other complaint category.",
)

# Choosing among the call's open complaints.
_OPEN_COMPLAINTS_RULES = (
    "Choose the open complaint where a missing fact matters most for the ICR to act on "
    "it, and ask for that one fact; target_category is that complaint.",
    "Ask for one concrete fact (a date, an amount, a part, a name, a registration "
    "number). Never ask how the customer feels or about their experience in general.",
    "If no important fact is missing for any open complaint, respond with null.",
)

# What an ICR needs to find out to act on each built-in complaint.
WHAT_TO_FIND_OUT = {
    "Cost": "the amount quoted and the amount billed; whether extra work was approved first",
    "Hygiene": "what was left dirty, and where in the vehicle",
    "Hospitality": "what happened during the visit, and when",
    "Service Quality": "what is still wrong; when it was last repaired; the vehicle registration number",
    "Turnaround Time": "the date that was promised; when the vehicle is needed",
    "Communication": "which updates the customer did not get; how they want to be contacted",
    "Parts Availability": "which part is missing; when it was ordered",
    "Staff Behaviour": "who it was and when it happened",
    "Documentation": "which document is wrong or missing",
    "Other": "the one detail needed to act on it",
}

_GUARDRAILS = (
    "Ask for information that is still missing; do not repeat anything the conversation already states.",
    "Before you answer, check what the CUSTOMER has already said: never ask for a date, "
    "amount, bill, part, vehicle detail or event they already gave. If nothing about the "
    "target category is still missing, respond with null.",
    "Letters and numbers the customer read out may be garbled by speech recognition "
    '(e.g. "TNO9AB4 321" for registration TN 09 AB 4321); treat them as already given.',
    "The question is a suggestion for the ICR to ask the customer. Do not write as the ICR: "
    "no greetings, apologies, promises or statements on behalf of the company.",
    "Do not invent facts that are not present in the conversation.",
    "Respect the current complaint status when choosing what to ask.",
    "Keep the question concise and natural.",
)

_RESPONSE_SHAPE = (
    '{"question": "<string>", '
    '"target_category": "<exactly the target category above>", '
    '"priority": <non-negative integer>, '
    '"reason": "<string>", '
    '"confidence": <number between 0.0 and 1.0>}'
)

# ---- Several questions at once, the most relevant first ----

_RANKED_RULES = (
    "Suggest up to {limit} questions, the most useful first: those whose missing fact "
    "matters most for the ICR to act on an open complaint. target_category is the "
    "complaint the question is about.",
    "Each question asks for one concrete fact (a date, an amount, a part, a name, a "
    "registration number), and for a different fact from the other questions. Never ask "
    "how the customer feels or about their experience in general.",
    "Suggest fewer questions, or none, when fewer facts are missing.",
)

_RANKED_SHAPE = (
    '{"question": "<string>", '
    '"target_category": "<one of the open complaints above>", '
    '"reason": "<string>"}'
)

_TRANSLATED_RANKED_SHAPE = (
    '{"question": "<string, in {language} script>", '
    '"question_en": "<the same question in English>", '
    '"target_category": "<one of the open complaints above>", '
    '"reason": "<string, in English>"}'
)

# Inside a combined live-analysis request the open complaints are the ones
# that same answer reports.
_LIVE_TARGET = "<a complaint category you report in TASK 1>"

_TRANSLATED_RESPONSE_SHAPE = (
    '{"question": "<string, in {language} script>", '
    '"question_en": "<the same question in English>", '
    '"target_category": "<exactly the target category above>", '
    '"priority": <non-negative integer>, '
    '"reason": "<string, in English>", '
    '"confidence": <number between 0.0 and 1.0>}'
)


class _InvalidResponse(Exception):
    pass


class LLMQuestionProvider(QuestionSuggestionProvider):
    """Suggests the next question with the LLM, in the customer's language.

    fallback (e.g. the rule-based questions) answers instead when the LLM
    fails or its answer is unusable, such as a Tamil question not written in
    Tamil script. A deliberate "nothing to ask yet" is not replaced."""

    def __init__(
        self,
        llm_client: LLMClient,
        fallback: QuestionSuggestionProvider | None = None,
        check_answered: bool = False,
        check_client: LLMClient | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._fallback = fallback
        # The model that checks suggestions (default: the one that writes
        # them). A larger model judges "already said?" far more reliably.
        self._check_client = check_client or llm_client
        # Each suggestion is checked against what the customer already said;
        # one asking for that is replaced once, else nothing is suggested.
        self._check_answered = check_answered

    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        try:
            suggestion = self._ask(context)
            if suggestion is None or not self._check_answered:
                return suggestion
            answered = self._answered_by_customer(suggestion, context)
            if answered is None:
                return suggestion
            # One more try with that question ruled out.
            context = replace(
                context, answered_questions=(*context.answered_questions, answered)
            )
            suggestion = self._ask(context)
            if suggestion is None or self._answered_by_customer(suggestion, context) is None:
                return suggestion
            return None
        except _InvalidResponse as exc:
            logger.warning("Discarding invalid LLM question response: %s", exc)
        except Exception:
            if self._fallback is None:
                raise
            logger.exception("LLM question suggestion failed")
        if self._fallback is None:
            return None
        return self._fallback.generate(context)

    # ---- Several questions, the most relevant first ----

    def generate_ranked(
        self, context: QuestionGenerationContext, limit: int
    ) -> tuple[QuestionSuggestion, ...]:
        """Up to `limit` questions in one request, then one check of them
        all against what the customer has already said."""
        try:
            response = self._llm_client.complete(self._build_ranked_request(context, limit))
            suggestions = self.parse_ranked(_decode(response.text), context, limit)
            if suggestions is None:
                raise _InvalidResponse("the answer is not a list of questions")
            return self.checked(suggestions, context)
        except _InvalidResponse as exc:
            logger.warning("Discarding invalid LLM question response: %s", exc)
        except Exception:
            if self._fallback is None:
                raise
            logger.exception("LLM question suggestion failed")
        if self._fallback is None:
            return ()
        return self._fallback.generate_ranked(context, limit)

    def _ranked_rules(self, context: QuestionGenerationContext, limit: int) -> str:
        handled = (
            (
                "Do not suggest these questions again (the ICR has already accepted or "
                "skipped them): " + "; ".join(context.handled_questions),
            )
            if context.handled_questions
            else ()
        )
        return "\n".join(
            f"- {rule}"
            for rule in (
                *(rule.replace("{limit}", str(limit)) for rule in _RANKED_RULES),
                *_RANKED_GUARDRAILS,
                *handled,
                *_language_rules(context),
            )
        )

    @staticmethod
    def _ranked_shape(context: QuestionGenerationContext) -> str:
        if context.language == ENGLISH:
            return _RANKED_SHAPE
        return _TRANSLATED_RANKED_SHAPE.replace("{language}", language_name(context.language))

    def _build_ranked_request(
        self, context: QuestionGenerationContext, limit: int
    ) -> LLMRequest:
        complaints = context.open_complaints or (
            OpenComplaint(context.category, context.status),
        )
        target = "Open complaints (status; what the ICR needs to find out):\n" + "".join(
            f"- {c.category} ({c.status.value}): "
            f"{WHAT_TO_FIND_OUT.get(c.category) or c.description or 'the details needed to act on it'}\n"
            for c in complaints
        )
        prompt = (
            "You assist a human ICR (customer service representative) during a live "
            "automotive service call. You only suggest questions; the ICR decides "
            "whether to ask them.\n\n"
            f"{target}"
            f"Conversation so far:\n{self._conversation_text(context) or _NO_CONVERSATION}\n\n"
            f"Rules:\n{self._ranked_rules(context, limit)}\n\n"
            f"{format_learning_guidance(context.learning_context)}"
            f"Respond with ONLY a JSON array of at most {limit} items and nothing else "
            "(no markdown, no commentary), the most useful question first, each item in "
            "exactly this shape:\n"
            f"{self._ranked_shape(context)}\n"
            "If no important fact is missing for any open complaint, respond with exactly: []"
        )
        return LLMRequest(prompt=prompt)

    def ranked_task(self, context: QuestionGenerationContext, limit: int) -> str:
        """This provider's task inside a combined live-analysis request (see
        LLMLiveAnalysisProvider): the same rules and guidance as its own
        request for several questions. The conversation is in that request
        already, and the open complaints are the ones its answer reports."""
        hints = "".join(f"- {category}: {hint}\n" for category, hint in WHAT_TO_FIND_OUT.items())
        shape = self._ranked_shape(context).replace(
            "<one of the open complaints above>", _LIVE_TARGET
        )
        return (
            "The open complaints are the ones you report in TASK 1. What the ICR needs to "
            "find out about a complaint, by category (for a category not listed here: the "
            "details needed to act on it):\n"
            f"{hints}\n"
            f"Rules:\n{self._ranked_rules(context, limit)}\n\n"
            f"{format_learning_guidance(context.learning_context)}"
            f'"questions" is a JSON array of at most {limit} items, the most useful '
            f"question first, each item in exactly this shape:\n{shape}\n"
            'If no important fact is missing for any open complaint, "questions" is [].'
        )

    def parse_ranked(
        self, data: Any, context: QuestionGenerationContext, limit: int
    ) -> tuple[QuestionSuggestion, ...] | None:
        """The questions in a decoded answer, in its order, each checked as
        a single suggestion is (its complaint must be open, its language the
        customer's). One unusable question is left out and the rest kept;
        None when the answer is not a list of questions at all."""
        if not isinstance(data, list):
            return None
        handled = {text.casefold() for text in context.handled_questions}
        suggestions: list[QuestionSuggestion] = []
        seen: set[str] = set()
        unusable = 0
        for item in data:
            if len(suggestions) >= limit:
                break
            try:
                if not isinstance(item, dict):
                    raise TypeError("each question must be an object")
                suggestion = self._build_suggestion(
                    {"priority": len(suggestions), **item}, context
                )
            except (TypeError, ValueError) as exc:
                unusable += 1
                logger.warning("Skipping an unusable suggested question: %s", exc)
                continue
            texts = {suggestion.question.casefold(), (suggestion.question_en or "").casefold()}
            if texts & handled or suggestion.question.casefold() in seen:
                continue
            seen.add(suggestion.question.casefold())
            # Its place in the list is its priority (0: asked first).
            suggestions.append(replace(suggestion, priority=len(suggestions)))
        if unusable and not suggestions:
            return None
        return tuple(suggestions)

    def checked(
        self, suggestions: tuple[QuestionSuggestion, ...], context: QuestionGenerationContext
    ) -> tuple[QuestionSuggestion, ...]:
        """The suggestions without those asking for something the customer
        has already given, found with one request for all of them. A failed
        check keeps them all."""
        if not suggestions or not self._check_answered:
            return suggestions
        numbered = "\n".join(
            f"{number}. {s.question_en or s.question}"
            for number, s in enumerate(suggestions, start=1)
        )
        prompt = (
            "A call-centre assistant suggests questions for an ICR (customer service "
            "representative) to ask a customer during a live automotive service call.\n\n"
            f"Conversation so far:\n{self._conversation_text(context)}\n\n"
            f"Suggested questions:\n{numbered}\n\n"
            "For each question: has the customer already given the information it asks "
            "for (possibly in other words, e.g. the date they brought the car in, or that "
            "nobody asked them first)? Respond with ONLY one JSON object: "
            '{"answered": [<the numbers of the questions already answered>]}'
        )
        try:
            data = _decode(self._check_client.complete(LLMRequest(prompt=prompt)).text)
            answered = data["answered"]
            if not isinstance(answered, list):
                raise TypeError("answered must be a list of question numbers")
            numbers = {int(number) for number in answered if not isinstance(number, bool)}
        except Exception as exc:
            logger.warning("Could not check the suggested questions against the call: %s", exc)
            return suggestions
        kept = tuple(s for number, s in enumerate(suggestions, start=1) if number not in numbers)
        if len(kept) < len(suggestions):
            logger.info(
                "Dropping %d suggested question(s) the customer has already answered",
                len(suggestions) - len(kept),
            )
        # Their places close up.
        return tuple(replace(s, priority=rank) for rank, s in enumerate(kept))

    def _ask(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        response = self._llm_client.complete(self._build_request(context))
        return self._parse_response(response.text, context)

    def _answered_by_customer(
        self, suggestion: QuestionSuggestion, context: QuestionGenerationContext
    ) -> str | None:
        """The question (in English) when the customer has already given what
        it asks for, else None. Asked separately: checking one question
        against the call is more reliable than writing one that respects
        everything said. A failed check keeps the suggestion."""
        question = suggestion.question_en or suggestion.question
        prompt = (
            "A call-centre assistant suggests questions for an ICR (customer service "
            "representative) to ask a customer during a live automotive service call.\n\n"
            f"Conversation so far:\n{self._conversation_text(context)}\n\n"
            f"Suggested question: {question}\n\n"
            "Has the customer already given the information this question asks for "
            "(possibly in other words, e.g. the date they brought the car in, or that "
            "nobody asked them first)? Respond with ONLY one JSON object: "
            '{"already_answered": true or false, "where": "<the customer\'s words, or empty>"}'
        )
        try:
            data = json.loads(
                _strip_code_fence(self._check_client.complete(LLMRequest(prompt=prompt)).text)
            )
            answered = data["already_answered"]
            if not isinstance(answered, bool):
                raise TypeError("already_answered must be true or false")
        except Exception as exc:
            logger.warning("Could not check the suggested question against the call: %s", exc)
            return None
        if not answered:
            return None
        logger.info(
            "Dropping suggested question %r: the customer already said %r",
            question,
            str(data.get("where", ""))[:120],
        )
        return question

    @staticmethod
    def _conversation_text(context: QuestionGenerationContext) -> str:
        # Who said what, so the model can see what the customer already told.
        return "\n".join(
            f"{u.speaker_role.value}: {text}"
            for u in context.utterances
            if (text := u.transcript.strip())
        )

    def _build_request(self, context: QuestionGenerationContext) -> LLMRequest:
        choosing = bool(context.open_complaints)
        previous = (
            (
                "Do not suggest this question again (it was suggested last): "
                f"{context.previous_question.strip()}",
            )
            if context.previous_question and context.previous_question.strip()
            else ()
        )
        answered = (
            (
                "Do not suggest these questions: the customer has already given what they "
                "ask for: " + "; ".join(context.answered_questions),
            )
            if context.answered_questions
            else ()
        )
        rules = "\n".join(
            f"- {rule}"
            for rule in (
                *(_OPEN_COMPLAINTS_RULES if choosing else _ONE_CATEGORY_RULES),
                *_GUARDRAILS,
                *previous,
                *answered,
                *_language_rules(context),
            )
        )
        shape = (
            _RESPONSE_SHAPE
            if context.language == ENGLISH
            else _TRANSLATED_RESPONSE_SHAPE.replace(
                "{language}", language_name(context.language)
            )
        )
        if choosing:
            shape = shape.replace(
                "<exactly the target category above>", "<one of the open complaints above>"
            )
            target = "Open complaints (status; what the ICR needs to find out):\n" + "".join(
                f"- {c.category} ({c.status.value}): "
                f"{WHAT_TO_FIND_OUT.get(c.category) or c.description or 'the details needed to act on it'}\n"
                for c in context.open_complaints
            )
        else:
            target = (
                f"Target complaint category: {context.category}\n"
                f"Current complaint status: {context.status.value}\n"
            )
        prompt = (
            "You assist a human ICR (customer service representative) during a live "
            "automotive service call. You only suggest a question; the ICR decides "
            "whether to ask it.\n\n"
            f"{target}"
            f"Conversation so far:\n{self._conversation_text(context) or _NO_CONVERSATION}\n\n"
            f"Rules:\n{rules}\n\n"
            f"{format_learning_guidance(context.learning_context)}"
            "Respond with ONLY a single JSON object and nothing else "
            "(no markdown, no commentary), in exactly this shape:\n"
            f"{shape}\n"
            "priority must be a non-negative whole number and confidence a number "
            "between 0.0 and 1.0, not text.\n"
            "If the conversation does not contain enough information to ask a "
            "meaningful question, respond with exactly: null"
        )
        return LLMRequest(prompt=prompt)

    def _parse_response(
        self, text: str, context: QuestionGenerationContext
    ) -> QuestionSuggestion | None:
        if not isinstance(text, str):
            raise _InvalidResponse("response text is not a string")
        try:
            data = json.loads(_strip_code_fence(text))
        except json.JSONDecodeError as exc:
            raise _InvalidResponse("response is not valid JSON") from exc

        if data is None:
            return None
        if not isinstance(data, dict):
            raise _InvalidResponse("JSON response is not an object")

        try:
            return self._build_suggestion(data, context)
        except (TypeError, ValueError) as exc:
            raise _InvalidResponse(str(exc)) from exc

    @staticmethod
    def _build_suggestion(
        data: dict[str, Any], context: QuestionGenerationContext
    ) -> QuestionSuggestion:
        missing = [f for f in _REQUIRED_FIELDS if f not in data]
        if missing:
            raise ValueError(f"missing fields: {missing}")

        question = _require_str(data["question"], "question")
        reason = _require_str(data["reason"], "reason")
        category = _require_str(data["target_category"], "target_category")
        allowed = {c.category for c in context.open_complaints} or {context.category}
        # The model may copy a line of the list: "Service Quality (detected)".
        named = re.sub(r"\s*\([^)]*\)\s*$", "", category).casefold()
        category = next((a for a in allowed if a.casefold() == named), category)
        if category not in allowed:
            raise ValueError(f"target_category {category!r} is not one of {sorted(allowed)}")

        priority = data["priority"]
        if isinstance(priority, bool):
            raise ValueError("priority must be an integer")

        confidence = data.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise ValueError("confidence must be a number")
            confidence = float(confidence)

        question_en = None
        if context.language != ENGLISH:
            if not is_written_in_script(question, context.language):
                raise ValueError(
                    f"question is not written in {language_name(context.language)} script"
                )
            question_en = _require_str(data.get("question_en"), "question_en")

        return QuestionSuggestion(
            question=question,
            target_category=category,
            priority=priority,
            reason=reason,
            source=SuggestionSource.LLM,
            confidence=confidence,
            language=context.language,
            question_en=question_en,
        )


# For several questions: nothing missing about a complaint means no
# question about it, not an empty answer.
_RANKED_GUARDRAILS = tuple(
    rule.replace(
        "If nothing about the target category is still missing, respond with null.",
        "Suggest no question about a complaint when nothing about it is still missing.",
    )
    for rule in _GUARDRAILS
)


def _decode(text: Any) -> Any:
    try:
        return decode_json(text)
    except UnusableAnswer as exc:
        raise _InvalidResponse(str(exc)) from exc


def _language_rules(context: QuestionGenerationContext) -> tuple[str, ...]:
    if context.language == ENGLISH:
        return ("Write the question in English.",)
    name = language_name(context.language)
    return (
        f'The customer speaks {name}. Write "question" in {name}, in {name} script '
        f"only, even when the customer speaks {name} in Latin letters or mixes in "
        "English. English words the customer used (e.g. part names) may be written "
        f"in {name} script as they are spoken.",
        'Write "question_en" as the same question in English, and "reason" in English.',
    )


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value.strip()


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()