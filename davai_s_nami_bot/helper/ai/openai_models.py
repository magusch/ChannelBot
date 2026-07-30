# -*- coding: utf-8 -*-
"""Model-aware parameter handling for the OpenAI chat.completions API.

Newer OpenAI models (gpt-5.x, o-series) changed the request contract, and not
uniformly — verified against the live API (July 2026):

| param              | gpt-4o | o4-mini | gpt-5-mini | gpt-5.4-mini |
|--------------------|--------|---------|------------|--------------|
| max_tokens         |   ok   | **400** |  **400**   |   **400**    |
| max_completion_tok |   ok   |   ok    |    ok      |     ok       |
| temperature != 1   |   ok   | **400** |  **400**   |  **400**¹    |
| reasoning_effort   | **400**|   ok    |    ok      |     ok       |
| verbosity          | **400**| **400** |    ok      |     ok       |

¹ gpt-5.4-mini takes a custom temperature only while reasoning is off
(``reasoning_effort="none"``); with reasoning active it demands the default 1.
That's why temperature is simply never sent to the reasoning families.

So there is no single kwargs set that works everywhere, and the matrix keeps
shifting with each release. Instead of hardcoding it per model we build a
best-guess kwargs set from the model family and then let
:func:`create_chat_completion` drop whatever the API rejects (400 with a
``param``) and retry — a new model only costs one wasted request, never a crash.

Only OpenAI-family model names are rewritten, so OpenAI-compatible endpoints
(Gemini, Perplexity) keep their legacy ``max_tokens`` contract untouched.
"""

import logging

from openai import BadRequestError

log = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"

# Families that reject `max_tokens` and accept `reasoning_effort`.
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")

# Tuning params that may be rejected per model; safe to drop and retry without.
_OPTIONAL_PARAMS = ("verbosity", "reasoning_effort", "temperature")


def is_reasoning_model(model):
    """True for gpt-5.x / o-series models (new request contract)."""
    return str(model or "").lower().startswith(_REASONING_PREFIXES)


def chat_kwargs(
    model,
    *,
    temperature=None,
    max_tokens=None,
    reasoning_effort=None,
    verbosity=None,
):
    """Build chat.completions kwargs adapted to ``model``.

    ``max_tokens`` is renamed to ``max_completion_tokens`` for the new families
    (they reject the legacy name outright), ``temperature`` is dropped for them
    (see the note above), and ``reasoning_effort``/``verbosity`` are only sent to
    models that can have them.
    """
    kwargs = {}
    reasoning = is_reasoning_model(model)

    if max_tokens is not None:
        kwargs["max_completion_tokens" if reasoning else "max_tokens"] = max_tokens
    if temperature is not None and not reasoning:
        kwargs["temperature"] = temperature
    if reasoning:
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
        if verbosity is not None:
            kwargs["verbosity"] = verbosity
    return kwargs


def create_chat_completion(client, model, messages, **kwargs):
    """chat.completions.create that self-heals on rejected tuning params.

    On a 400 naming a parameter we sent (e.g. ``temperature`` on gpt-5-mini,
    ``verbosity`` on o4-mini), that parameter is dropped and the call retried,
    so an unfamiliar model degrades to a plain request instead of failing the
    whole event preparation. Errors we can't fix by dropping a param propagate.
    """
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    for _ in range(len(_OPTIONAL_PARAMS) + 1):
        try:
            return client.chat.completions.create(
                model=model, messages=messages, **kwargs
            )
        except BadRequestError as e:
            dropped = _param_to_drop(e, kwargs)
            if dropped is None:
                raise
            log.warning(
                f"model={model} rejected {dropped}={kwargs[dropped]!r}, "
                f"retrying without it ({e})"
            )
            kwargs.pop(dropped)
    raise RuntimeError("unreachable: retry budget exhausted")


def _param_to_drop(error, kwargs):
    """Name of the optional param the API complained about, or None."""
    body = getattr(error, "body", None)
    param = getattr(error, "param", None) or (
        body.get("param") if isinstance(body, dict) else None
    )
    message = str(error)
    for name in _OPTIONAL_PARAMS:
        if name not in kwargs:
            continue
        if param == name or f"'{name}'" in message:
            return name
    return None
