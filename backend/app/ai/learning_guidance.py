"""Renders approved learning improvements as prompt guidance for LLM providers."""

from collections.abc import Sequence

from app.domain.improvement_candidate import ImprovementSpecification
from app.domain.runtime_improvement_context import RuntimeImprovementContext

# Bounds prompt growth; the most recently activated improvements come last
# in the repository order, so keep those.
MAX_GUIDANCE_ITEMS = 10


# How improvements approved before the instruction was written per
# component described their change: not something to tell the AI.
_LEGACY_PROPOSAL = "Investigate and address the recurring"


def guidance_text(specification: ImprovementSpecification) -> str:
    """The one line an approved improvement adds to the AI's instructions:
    what to do differently and how strong the evidence is."""
    if specification.proposed_behavior.startswith(_LEGACY_PROPOSAL):
        return specification.current_behavior
    return specification.proposed_behavior


def format_learning_guidance(contexts: Sequence[RuntimeImprovementContext]) -> str:
    """Return a prompt section for the given improvements, or "" if none.

    The guidance is advisory: it is placed after the provider's own rules and
    explicitly ranks below them, so it can never override a guardrail.
    """
    if not contexts:
        return ""

    items = "\n".join(
        f"- {guidance_text(context.specification)}"
        for context in list(contexts)[-MAX_GUIDANCE_ITEMS:]
    )
    return (
        "Corrections approved by human reviewers from past calls. Take them into "
        "account only where this conversation is genuinely similar; the rules "
        f"above always take priority:\n{items}\n\n"
    )
