"""Reviewed AI outputs as a training file.

Nothing in this system trains a model: the speech and language models are
the providers'. What it does collect is the raw material for training one:
every AI output a person has judged (a complaint category or a tone they
corrected, a suggested question they found helpful or not), with the
transcript it was made from. This module writes those as JSON Lines, one
example per line, ready for the day a model is fine-tuned.

Each line has the task, the transcript, what the AI said, what is correct
and who judged it. Lines with a known correct answer also carry "messages"
(system, user, assistant), the shape chat-model fine-tuning takes. A
question judged not helpful has no correct answer: it is kept, without
messages, as an example of what not to say.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.ai.llm.transcript import numbered_transcript
from app.domain.conversation import Conversation
from app.domain.learning_evidence import LearningComponent
from app.domain.learning_feedback import FeedbackType, LearningFeedback
from app.domain.learning_observation import LearningObservation

FORMAT_VERSION = 1
QUESTION_HELPFUL = "helpful"

# What the model is asked to do, per task, in a fine-tuning example.
_INSTRUCTIONS = {
    LearningComponent.COMPLAINT_DETECTION: (
        "You read a transcript of an automotive service call between an ICR (customer "
        "service representative) and a customer. Name the complaint category the customer "
        "raises in the part described, or say that it is not a complaint."
    ),
    LearningComponent.SENTIMENT_ANALYSIS: (
        "You read a transcript of an automotive service call between an ICR (customer "
        "service representative) and a customer. Give the customer's overall tone as one "
        "of POSITIVE, NEUTRAL, NEGATIVE, FRUSTRATED or ESCALATING."
    ),
    LearningComponent.NEXT_QUESTION: (
        "You read a transcript of an automotive service call between an ICR (customer "
        "service representative) and a customer. Suggest the next question the ICR should "
        "ask the customer."
    ),
}
_DEFAULT_INSTRUCTION = (
    "You read a transcript of an automotive service call between an ICR (customer service "
    "representative) and a customer, and produce the output described."
)


@dataclass(frozen=True)
class ReviewedOutput:
    """An AI output and the judgement a person gave on it."""

    observation: LearningObservation
    feedback: LearningFeedback


@dataclass(frozen=True)
class TrainingExport:
    # JSON Lines, UTF-8.
    content: bytes
    examples: int
    # Of those, with a correct answer and a transcript: usable for fine-tuning.
    with_messages: int
    # Counted per task.
    by_task: dict[str, int]


def _verdict(feedback: LearningFeedback) -> tuple[str, str | None]:
    """("corrected" | "confirmed" | "rejected", the correct output or None)."""
    if feedback.feedback_type is FeedbackType.HUMAN_CORRECTION:
        return "corrected", feedback.corrected_value
    if feedback.outcome == QUESTION_HELPFUL:
        return "confirmed", feedback.original_value
    return "rejected", None


def training_example(reviewed: ReviewedOutput, conversation: Conversation | None) -> dict:
    observation, feedback = reviewed.observation, reviewed.feedback
    verdict, correct = _verdict(feedback)
    if verdict == "confirmed" and correct is None:
        correct = observation.predicted_value
    transcript = None
    if conversation is not None and conversation.utterances:
        transcript = numbered_transcript(conversation)
    example = {
        "format": FORMAT_VERSION,
        "task": observation.component.value,
        "call_id": observation.call_id,
        "about": observation.description,
        "transcript": transcript,
        "ai_output": observation.predicted_value,
        "ai_confidence": observation.confidence,
        "verdict": verdict,
        "correct_output": correct,
        "judged_by": feedback.source.value,
        "judged_at": feedback.created_at,
        "notes": feedback.notes,
    }
    if correct is not None and transcript is not None:
        instruction = _INSTRUCTIONS.get(observation.component, _DEFAULT_INSTRUCTION)
        example["messages"] = [
            {"role": "system", "content": instruction},
            {
                "role": "user",
                "content": f"Transcript:\n{transcript}\n\nAbout: {observation.description}",
            },
            {"role": "assistant", "content": correct},
        ]
    return example


def export_training_data(
    reviewed: Iterable[ReviewedOutput],
    get_call: Callable[[str], Conversation | None],
) -> TrainingExport:
    """get_call: the call with that id, or None when it is gone (the
    example is then kept without its transcript)."""
    lines: list[str] = []
    with_messages = 0
    by_task: dict[str, int] = {}
    calls: dict[str, Conversation | None] = {}
    for item in sorted(reviewed, key=lambda r: (r.feedback.created_at, r.feedback.feedback_id)):
        call_id = item.observation.call_id
        if call_id not in calls:
            calls[call_id] = get_call(call_id)
        example = training_example(item, calls[call_id])
        with_messages += "messages" in example
        by_task[example["task"]] = by_task.get(example["task"], 0) + 1
        lines.append(json.dumps(example, ensure_ascii=False))
    content = ("\n".join(lines) + "\n" if lines else "").encode("utf-8")
    return TrainingExport(content, len(lines), with_messages, by_task)
