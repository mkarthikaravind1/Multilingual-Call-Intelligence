"""Reading the JSON an LLM was asked for, and asking once more when the
answer cannot be used.

A model sometimes wraps its JSON in a sentence or a code fence, cuts it
short, or answers in another shape. The first two are read here without a
new request where possible; anything still unusable is asked for a second
time, and only then given up on.
"""

import json
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar

from app.ai.llm.client import LLMClient, LLMRequest
from app.observability.metrics import LLM_UNUSABLE_ANSWERS

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRY_NOTE = (
    "\n\nYour previous answer to this request could not be read as the JSON asked for "
    "above. Answer again with ONLY that JSON, complete and valid, and nothing else."
)
# How much of an unusable answer is logged, to show what went wrong.
_EXCERPT_CHARS = 300
_OPENING_BRACKET = re.compile(r"[\[{]")


class UnusableAnswer(Exception):
    """The LLM's answer is not the JSON it was asked for."""


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```")
    return text.strip()


def decode_json(text: Any) -> Any:
    """The JSON value in an LLM answer: the answer itself, or the array or
    object inside a code fence or surrounding commentary. Raises
    UnusableAnswer when there is none."""
    if not isinstance(text, str):
        raise UnusableAnswer("response text is not a string")
    cleaned = strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # "Here are the complaints: [...]": read from the first bracket. Only
    # the outermost value is tried, so a cut-short answer is never
    # mistaken for one of the smaller values inside it.
    opening = _OPENING_BRACKET.search(cleaned)
    if opening is not None:
        try:
            value, _ = json.JSONDecoder().raw_decode(cleaned, opening.start())
            return value
        except json.JSONDecodeError:
            pass
    raise UnusableAnswer("response is not valid JSON")


def ask_for_json(
    llm_client: LLMClient,
    request: LLMRequest,
    parse: Callable[[Any], T],
    task: str,
) -> T:
    """The parsed answer to `request`. `parse` takes the answer's text and
    raises UnusableAnswer when it cannot be used; the request is then sent
    once more, saying so. Raises UnusableAnswer when the second answer is
    unusable too. A failing request (rate limit, network) is not retried
    here and raises as it always did. task: the name it is counted under."""
    response = llm_client.complete(request)
    try:
        return parse(response.text)
    except UnusableAnswer as exc:
        logger.warning(
            "Unusable LLM %s answer (%s); asking once more. Answer began: %s",
            task,
            exc,
            _excerpt(response.text),
        )

    try:
        response = llm_client.complete(LLMRequest(prompt=request.prompt + RETRY_NOTE))
        result = parse(response.text)
    except UnusableAnswer as exc:
        LLM_UNUSABLE_ANSWERS.inc(task, "dropped")
        logger.warning(
            "Unusable LLM %s answer again (%s); giving up. Answer began: %s",
            task,
            exc,
            _excerpt(response.text),
        )
        raise
    except Exception:
        LLM_UNUSABLE_ANSWERS.inc(task, "dropped")
        raise
    LLM_UNUSABLE_ANSWERS.inc(task, "recovered")
    return result


def _excerpt(text: Any) -> str:
    if not isinstance(text, str):
        return repr(text)
    return repr(text[:_EXCERPT_CHARS]) + ("..." if len(text) > _EXCERPT_CHARS else "")
