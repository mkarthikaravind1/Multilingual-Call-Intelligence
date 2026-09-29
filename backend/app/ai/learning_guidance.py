"""Renders approved learning improvements as prompt guidance for LLM providers."""

from collections.abc import Sequence

from app.domain.runtime_improvement_context import RuntimeImprovementContext

# Bounds prompt growth; the most recently activated improvements come last
# in the repository order, so keep those.
MAX_GUIDANCE_ITEMS = 10


def format_learning_guidance(contexts: Sequence[RuntimeImprovementContext]) -> str:
    """Return a prompt section for the given improvements, or "" if none.

    The guidance is advisory: it is placed after the provider's own rules and
    explicitly ranks below them, so it can never override a guardrail.
    """
    if not contexts:
        return ""

    items = "\n".join(
        f"- {context.specification.current_behavior}"
        for context in list(contexts)[-MAX_GUIDANCE_ITEMS:]
    )
    return (
        "Corrections approved by human reviewers from past calls. Take them into "
        "account only where this conversation is genuinely similar; the rules "
        f"above always take priority:\n{items}\n\n"
    )
