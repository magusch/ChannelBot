# -*- coding: utf-8 -*-
"""Parsing of model answers for event preparation.

All three copywriting helpers (OpenAI, Gemini, Claude) ask for the same JSON
object and used to parse it the same way: ``json.loads``, and on failure fall
back to the pre-JSON ``key => value`` format, stuffing the **whole raw answer**
into the text field. That fallback silently published broken output: on prod
6-10% of prepared events since late July 2026 had the entire JSON blob sitting
in ``prepared_text`` (ids 15519, 15536, 15545, 15578, 15631, 15670, …).

The answers themselves were nearly fine — the model emitted one extra ``}`` or
dropped the final one (truncated output), which ``json.loads`` rejects outright.
So we repair instead of giving up:

* trailing junk after the object → ``raw_decode`` reads the first complete value;
* truncated tail → reopen the structures the answer left dangling and re-parse.

And when the answer really is unusable, we return ``{}`` rather than a raw dump:
``celery_tasks.update_event`` skips events without ``prepared_text``, leaving
``is_ready`` unset so the event is picked up again by the next prep round —
strictly better than a published post containing JSON.
"""

import json
import logging

log = logging.getLogger(__name__)

# Keys of the legacy "key => value" answer format, mapped downstream by the
# helpers' `replace_phrases`. Kept for prompts/models that still answer that way.
_LEGACY_SEPARATOR = '=>'


def parse_event_answer(raw):
    """Model answer → dict of event fields. ``{}`` when nothing usable is left.

    Adds ``full_answer`` (the untouched answer) on success, as the helpers'
    callers expect.
    """
    if not raw:
        return {}

    text = _strip_code_fence(str(raw).strip())

    if '{' in text:
        data = _load_json(text)
        if data is not None:
            data['full_answer'] = raw
            return data
        log.error(
            f"AI answer looks like JSON but could not be parsed even after "
            f"repair; dropping it (len={len(text)}, tail={text[-80:]!r})"
        )
        return {}

    return _parse_legacy(text, raw)


def _strip_code_fence(text):
    """Remove a leading ```/```json fence and its closing counterpart."""
    if not text.startswith('```'):
        return text
    text = text.split('\n', 1)[1] if '\n' in text else text[3:]
    return text.rsplit('```', 1)[0].strip()


def _load_json(text):
    """Parse the first JSON object in ``text``, repairing a truncated tail."""
    start = text.find('{')
    if start == -1:
        return None
    candidate = text[start:]

    for attempt in (candidate, _close_dangling(candidate)):
        if attempt is None:
            continue
        try:
            # raw_decode stops at the end of the first complete value, so any
            # trailing junk (a duplicated closing brace, stray prose) is ignored.
            data, _ = json.JSONDecoder().raw_decode(attempt)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _close_dangling(text):
    """Close structures a truncated answer left open, or None if unbalanceable.

    Walks the text tracking string context (so braces inside values don't
    count), then appends the missing quote/brackets in reverse order.
    """
    stack = []
    in_string = False
    escaped = False

    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '{[':
            stack.append('}' if char == '{' else ']')
        elif char in '}]':
            if not stack or stack.pop() != char:
                return None

    if not in_string and not stack:
        return None  # already balanced: repair wouldn't change anything

    repaired = text
    if in_string:
        repaired += '"'
    # A truncation can land mid-key ("addre) — drop the incomplete pair so the
    # rest of the object still parses.
    repaired = repaired.rstrip().rstrip(',')
    return repaired + ''.join(reversed(stack))


def _parse_legacy(text, raw):
    """Pre-JSON answer format: lines of ``ключ => значение;``."""
    event_data = {}
    for line in text.split('\n'):
        if not line.strip():
            continue
        parts = line.split(_LEGACY_SEPARATOR)
        if len(parts) >= 2:
            value = parts[-1].strip().replace(';', '')
            if value:
                event_data[parts[0].strip().lower()] = value

    if not event_data:
        log.warning("AI answer matched no known format, dropping it")
        return {}

    if len(event_data.get('текст', '').strip()) < 100:
        event_data['текст'] = text
    event_data['full_answer'] = raw
    return event_data
