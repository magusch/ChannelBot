"""Themed digest posts: pure assembly helpers (no DB, no network, no AI).

Rendering lives here rather than in the AI because two things cannot be
delegated to a prompt: the Telegram caption limit (1024 chars, enforced by
shrinking comments then dropping events) and MarkdownV2 escaping.
"""

import math
import re
from datetime import datetime

# Telegram limits: photo caption vs plain text.
TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_TEXT_LIMIT = 4096

# Below the caption limit: visible_length is an estimate, so leave headroom.
DEFAULT_POST_LIMIT = 1000

# Comment budgets tried in order before events start being dropped.
DEFAULT_COMMENT_STEPS = (110, 85, 60, 40, 0)

MAX_TITLE_CHARS = 60

_MD2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"
_MD2_ESCAPE_RE = re.compile("([" + re.escape(_MD2_SPECIAL) + "])")

_MONTHS_SHORT = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}
_MONTHS_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября",
    12: "декабря",
}
_WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
_WEEKDAYS_TITLE = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

LAYOUT_DETAILED = "detailed"
LAYOUT_COMPACT = "compact"
LAYOUT_BY_DAY = "by_day"
LAYOUT_PROSE = "prose"

# Sentence end used when prose has to be trimmed to fit the budget.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+")

# ``{{15418}}`` or ``{{15418|своими словами}}`` — written by the model,
# resolved here, so a hallucinated id costs a link and not the post.
PROSE_REF_RE = re.compile(r"\{\{\s*(\d+)\s*(?:\|([^}]*))?\}\}")


# --- Text primitives --------------------------------------------------------

def escape_md2(text):
    """Escape text for Telegram MarkdownV2 body content."""
    if not text:
        return ""
    return _MD2_ESCAPE_RE.sub(r"\\\1", str(text))


def escape_md2_url(url):
    """Escape a URL for use inside ``(...)`` of a MarkdownV2 inline link."""
    if not url:
        return ""
    return str(url).replace("\\", "\\\\").replace(")", "\\)")


def visible_length(text):
    """Characters Telegram counts against the caption/message limit.

    Telegram measures the *rendered* text: inline-link URLs become entity
    metadata and do not count, and markdown markers plus their escaping
    backslashes are not part of the output either. This mirrors that, so the
    budget is spent on what the reader actually sees.

    An estimate, not a reimplementation of Telegram's UTF-16 accounting — hence
    :data:`DEFAULT_POST_LIMIT` sits below :data:`TELEGRAM_CAPTION_LIMIT`.
    """
    if not text:
        return 0
    rendered = re.sub(r"\[([^\]]*)\]\((?:[^)\\]|\\.)*\)", r"\1", text)
    rendered = re.sub(r"\\(.)", r"\1", rendered)
    rendered = re.sub(r"[*_`]", "", rendered)
    return len(rendered)


def shorten(text, max_chars):
    """Trim to ``max_chars`` on a word boundary, adding an ellipsis when cut."""
    text = (text or "").strip()
    if max_chars is None or max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rstrip()
    space = cut.rfind(" ")
    if space > max_chars // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:—-") + "…"


def fmt_compact_date(from_date, to_date=None):
    """Short human date for a digest line: ``сб 9 авг, 19:00``."""
    if not isinstance(from_date, datetime):
        return ""

    start = f"{_WEEKDAYS_SHORT[from_date.weekday()]} {from_date.day} {_MONTHS_SHORT[from_date.month]}"

    if isinstance(to_date, datetime) and to_date.date() > from_date.date():
        if to_date.month == from_date.month:
            return f"{from_date.day}–{to_date.day} {_MONTHS_SHORT[from_date.month]}"
        return (
            f"{from_date.day} {_MONTHS_SHORT[from_date.month]} – "
            f"{to_date.day} {_MONTHS_SHORT[to_date.month]}"
        )

    if from_date.hour or from_date.minute:
        return f"{start}, {from_date.hour:02d}:{from_date.minute:02d}"
    return start


def fmt_price(event):
    """Price for a digest line: ``бесплатно`` / ``500₽`` / the raw string / ``""``.

    ``price_int`` uses ``-1`` for "could not parse the source price"
    (``PostHelper.price_int``), so anything negative falls through to the
    original text rather than being printed as a price of −1₽.
    """
    price_int = event.get("price_int")
    if price_int == 0:
        return "бесплатно"
    if isinstance(price_int, int) and price_int > 0:
        return f"{price_int}₽"
    price = (event.get("price") or "").strip()
    return shorten(price, 20)


PLACE_MAX_CHARS = 32


def event_place_name(event, max_chars=PLACE_MAX_CHARS):
    """Short venue label: the Place name, else the first part of the address."""
    place = event.get("place") or {}
    name = (place.get("place_name") or "").strip()
    if name:
        return shorten(name, max_chars) if max_chars else name
    address = (event.get("address") or "").strip()
    if address:
        first = address.split(",")[0]
        return shorten(first, max_chars) if max_chars else first
    return ""


def event_link(event):
    """Best outbound link for an event — tickets first, then the source page."""
    return (event.get("ticket_url") or event.get("url") or "").strip()


# --- Selection --------------------------------------------------------------

def cap_per_place(events, max_per_place):
    """Keep at most ``max_per_place`` events per venue, preserving input order."""
    if not max_per_place or max_per_place <= 0:
        return list(events)

    seen = {}
    kept = []
    for event in events:
        key = event.get("place_id") or (event.get("place") or {}).get("id")
        if key is None:
            kept.append(event)
            continue
        if seen.get(key, 0) >= max_per_place:
            continue
        seen[key] = seen.get(key, 0) + 1
        kept.append(event)
    return kept


def drop_recent(events, recent_ids):
    """Drop events that already appeared in a recent themed post."""
    if not recent_ids:
        return list(events)
    recent = set(recent_ids)
    return [e for e in events if e.get("id") not in recent]


def drop_categories(events, category_ids):
    """Drop whole categories from a selection."""
    if not category_ids:
        return list(events)
    excluded = set(category_ids)
    return [e for e in events if e.get("main_category_id") not in excluded]


def keep_starting_within(events, date_from, date_to):
    """Keep only events that *start* inside the window."""
    if date_from is None and date_to is None:
        return list(events)

    kept = []
    for event in events:
        start = event.get("from_date")
        day = start.date() if hasattr(start, "date") else start
        if day is None:
            kept.append(event)
            continue
        if date_from is not None and day < date_from:
            continue
        if date_to is not None and day > date_to:
            continue
        kept.append(event)
    return kept


def drop_long_runners(events, max_duration_days):
    """Drop events that run longer than ``max_duration_days``."""
    if not max_duration_days or max_duration_days <= 0:
        return list(events)

    kept = []
    for event in events:
        start, end = event.get("from_date"), event.get("to_date")
        if not hasattr(start, "date") or not hasattr(end, "date"):
            kept.append(event)
            continue
        if (end.date() - start.date()).days > max_duration_days:
            continue
        kept.append(event)
    return kept


def fmt_day_header(day):
    """``Сб, 8 августа`` — the day label for a by-day digest."""
    if day is None:
        return "Скоро"
    return f"{_WEEKDAYS_TITLE[day.weekday()]}, {day.day} {_MONTHS_GEN[day.month]}"


def group_by_day(events):
    """``[(day, [event, ...]), ...]`` in chronological order."""
    buckets = {}
    for event in events:
        start = event.get("from_date")
        day = start.date() if hasattr(start, "date") else None
        buckets.setdefault(day, []).append(event)

    dated = sorted((d for d in buckets if d is not None))
    ordered = [(d, buckets[d]) for d in dated]
    if None in buckets:
        ordered.append((None, buckets[None]))
    return ordered


# --- Rendering --------------------------------------------------------------

def _event_meta(event):
    """``сб 8 авг, 19:00 · Место · 990₽`` — the parts that are never AI-written."""
    parts = [
        fmt_compact_date(event.get("from_date"), event.get("to_date")),
        event_place_name(event),
        fmt_price(event),
    ]
    return " · ".join(p for p in parts if p)


def _linked_title(event, max_chars=MAX_TITLE_CHARS):
    """Bold, linked, escaped event title."""
    title = shorten(event.get("title") or "", max_chars)
    link = event_link(event)
    if link:
        return f"*[{escape_md2(title)}]({escape_md2_url(link)})*"
    return f"*{escape_md2(title)}*"


def render_day_line(event):
    """One line under a day header: ``*Название* — 990₽``."""
    price = fmt_price(event)
    head = _linked_title(event)
    return f"{head} — {escape_md2(price)}" if price else head


def render_event_block(event, comment, comment_max, compact=False):
    """One event, either as a three-line block or as a single compact line."""
    title = shorten(event.get("title") or "", MAX_TITLE_CHARS)
    link = event_link(event)
    if link:
        head = f"*[{escape_md2(title)}]({escape_md2_url(link)})*"
    else:
        head = f"*{escape_md2(title)}*"

    meta = _event_meta(event)

    if compact:
        return f"{head}\n_{escape_md2(meta)}_" if meta else head

    lines = [head]
    text = shorten(comment or "", comment_max)
    if text:
        lines.append(escape_md2(text))
    if meta:
        lines.append(f"_{escape_md2(meta)}_")
    return "\n".join(lines)


def render_tail_line(event, max_title=48):
    """A "also on" line: ``[Название](url) — вт 18 авг · 500₽``."""
    parts = [
        fmt_compact_date(event.get("from_date"), event.get("to_date")),
        fmt_price(event),
    ]
    meta = " · ".join(p for p in parts if p)
    head = _linked_title(event, max_title)
    return f"{head} — {escape_md2(meta)}" if meta else head


def build_tail_block(events, label=""):
    """The short-lines block that follows the detailed part, or ``""``."""
    events = list(events)
    if not events:
        return ""
    lines = [f"*{escape_md2(label)}*"] if label else []
    lines.extend(render_tail_line(event) for event in events)
    return "\n".join(lines)


def render_prose(text, events, max_title=MAX_TITLE_CHARS):
    """AI prose + ``{{id}}`` references → escaped MarkdownV2 with inline links."""
    by_id = {}
    for event in events:
        try:
            by_id[int(event.get("id"))] = event
        except (TypeError, ValueError):
            continue

    out, used, pos = [], [], 0
    for match in PROSE_REF_RE.finditer(text or ""):
        out.append(escape_md2(text[pos : match.start()]))
        pos = match.end()

        event = by_id.get(int(match.group(1)))
        label = (match.group(2) or "").strip()
        if event is None:
            out.append(escape_md2(label))
            continue

        link = event_link(event)
        label = shorten(label or (event.get("title") or ""), max_title)
        if link:
            out.append(f"[{escape_md2(label)}]({escape_md2_url(link)})")
        else:
            out.append(f"*{escape_md2(label)}*")
        if event.get("id") not in used:
            used.append(event.get("id"))

    out.append(escape_md2(text[pos:] if text else ""))
    return "".join(out), used


def trim_sentences(text, max_chars):
    """Drop whole trailing sentences until ``text`` fits ``max_chars`` visible."""
    if max_chars is None or max_chars <= 0 or not text:
        return text or ""

    sentences = _SENTENCE_END_RE.split(text.strip())
    while len(sentences) > 1 and visible_length(" ".join(sentences)) > max_chars:
        sentences.pop()
    return " ".join(sentences)


def compose_post(
    header,
    events,
    comments,
    footer,
    comment_max,
    layout=LAYOUT_DETAILED,
    tail_events=(),
    tail_label="",
    prose="",
):
    """Assemble header + body + optional tail + footer into one MarkdownV2 post."""
    if layout == LAYOUT_PROSE:
        body = (prose or "").strip()
    elif layout == LAYOUT_BY_DAY:
        chunks = []
        for day, day_events in group_by_day(events):
            lines = [f"*{escape_md2(fmt_day_header(day))}*"]
            lines.extend(render_day_line(event) for event in day_events)
            chunks.append("\n".join(lines))
        body = "\n\n".join(chunks)
    else:
        compact = layout == LAYOUT_COMPACT
        blocks = [
            render_event_block(
                event, comments.get(event.get("id"), ""), comment_max, compact=compact
            )
            for event in events
        ]
        body = ("\n" if compact else "\n\n").join(blocks)

    parts = [header.strip()] if header else []
    if body:
        parts.append(body)
    tail = build_tail_block(tail_events, tail_label)
    if tail:
        parts.append(tail)
    if footer:
        parts.append(footer.strip())
    return "\n\n".join(p for p in parts if p)


def is_mentioned(event, text):
    """Whether a rendered post still names ``event`` — by link, else by title."""
    link = event_link(event)
    if link:
        return escape_md2_url(link) in text
    title = shorten(event.get("title") or "", MAX_TITLE_CHARS)
    return bool(title) and escape_md2(title) in text


def assemble_post(
    header,
    events,
    comments,
    footer,
    *,
    limit=DEFAULT_POST_LIMIT,
    min_events=3,
    comment_steps=DEFAULT_COMMENT_STEPS,
    layout=LAYOUT_DETAILED,
    tail_events=(),
    tail_label="",
    prose="",
):
    """Fit a themed digest into ``limit`` visible characters.

    Two levers, in order of increasing cost:

    1. shrink the per-event comments through ``comment_steps``;
    2. drop the least relevant event and start over at the widest comment.

    Only the second lever applies outside ``detailed``, which has no comments.
    ``compact`` does not raise the event ceiling much on its own (a detailed post
    facing the same budget ends up at zero-length comments anyway); ``by_day``
    genuinely does, because dropping the venue and the repeated date roughly
    halves the cost of a line. The event count is still the caller's ``shown``.

    ``min_events`` is a floor — below it we stop dropping and accept the
    shortest possible rendering, because a "digest" of one event is not a
    digest. With comments at 0 and titles capped at
    :data:`MAX_TITLE_CHARS`, that floor rendering is bounded well under the
    limit for any realistic header/footer, so this terminates in budget.

    Returns ``(text, kept_events)`` — the caller stores ``kept_events`` as what
    the post actually shows.
    """
    kept = list(events)
    tail = list(tail_events)
    if not kept and not tail and not prose:
        return (compose_post(header, [], comments, footer, 0, layout=layout), [])

    steps = comment_steps if layout == LAYOUT_DETAILED else (0,)

    def render(step, text=prose):
        return compose_post(
            header,
            kept,
            comments,
            footer,
            step,
            layout=layout,
            tail_events=tail,
            tail_label=tail_label,
            prose=text,
        )

    while True:
        for step in steps:
            text = render(step)
            if visible_length(text) <= limit:
                return text, kept + tail

        # The tail is the cheapest thing to lose: named, not described.
        if tail:
            tail.pop()
            continue

        if layout == LAYOUT_PROSE:
            # Prose is cut by whole sentences, which can take a mention with
            # it, so the shown set is recomputed from what survived.
            overflow = visible_length(render(0)) - limit
            trimmed = trim_sentences(prose, max(visible_length(prose) - overflow, 0))
            text = render(0, trimmed)
            return text, [e for e in kept if is_mentioned(e, text)]

        if len(kept) <= min_events:
            return render(steps[-1]), kept

        weakest = min(
            range(len(kept)),
            key=lambda i: (kept[i].get("relevance") or 0, -(kept[i].get("score") or 0)),
        )
        kept.pop(weakest)


def build_header(emoji, title, intro):
    """Post header: emoji + bold theme title + a one-sentence intro."""
    lines = [f"{emoji} *{escape_md2(title)}*" if emoji else f"*{escape_md2(title)}*"]
    intro = (intro or "").strip()
    if intro:
        lines.append("")
        lines.append(escape_md2(intro))
    return "\n".join(lines)


def footer_label(rest_count):
    """``Ещё 12 мероприятий по теме — в боте``, or ``""`` when nothing is left."""
    if not rest_count or rest_count <= 0:
        return ""
    return f"Ещё {rest_count} {_plural_events(rest_count)} по теме — в боте"


def build_footer(bot_url, rest_count=None, label=None):
    """Footer linking onward to the bot."""
    if not bot_url:
        return ""
    if label is None:
        label = footer_label(rest_count)
        if not label:
            return ""
    return f"[{escape_md2(label)}]({escape_md2_url(bot_url)})"


# --- Web-app deep links -----------------------------------------------------

# Telegram caps a `startapp` payload at 64 chars, alphabet A-Za-z0-9_- only.
TELEGRAM_STARTAPP_MAX = 64


def _day_str(value):
    """``YYYYMMDD`` for a date/datetime, or ``""``."""
    if value is None:
        return ""
    return f"{value.year:04d}{value.month:02d}{value.day:02d}"


def webapp_date_filter(date_from, date_to=None):
    """Date section for startapp: a single day or a range, both as ``YYYYMMDD``."""
    day_from = _day_str(date_from)
    if not day_from:
        return ""
    day_to = _day_str(date_to)
    if day_to and day_to != day_from:
        return f"date-{day_from}-{day_to}"
    return f"date-{day_from}"


def webapp_category_filter(category_ids):
    """Category section for startapp: ``cat-1-3-8``."""
    ids = [int(c) for c in (category_ids or []) if c]
    return "cat-" + "-".join(str(c) for c in ids) if ids else ""


def webapp_price_filter(price_max=None, free_only=False):
    """Price section for startapp: ``price-0`` (free) or ``price-1500``."""
    if free_only:
        return "price-0"
    if price_max:
        return f"price-{int(price_max)}"
    return ""


def webapp_startapp(*sections, max_len=TELEGRAM_STARTAPP_MAX):
    """``events__date-…__cat-…`` payload, trimmed to Telegram's length cap.

    Sections are given most-important-first and dropped from the end until the
    payload fits. Telegram rejects an over-long ``startapp``, so a category list
    that doesn't fit degrades to a date-only link rather than to a dead link.
    """
    parts = ["events"] + [s for s in sections if s]
    while len(parts) > 1 and len("__".join(parts)) > max_len:
        parts.pop()
    payload = "__".join(parts)
    return payload if len(payload) <= max_len else "events"


def webapp_link(bot_url, *sections):
    """Link to the web-app event list with filters applied."""
    if not bot_url:
        return ""
    return f"{bot_url.rstrip('/')}?startapp={webapp_startapp(*sections)}"


def webapp_event_link(bot_url, event_id):
    """Link to a single event's card in the web app."""
    if not bot_url:
        return ""
    return f"{bot_url.rstrip('/')}?startapp=event_{event_id}"


def _plural_events(n):
    """Russian plural for 'мероприятие' by count."""
    if 11 <= n % 100 <= 14:
        return "мероприятий"
    return {1: "мероприятие", 2: "мероприятия", 3: "мероприятия", 4: "мероприятия"}.get(
        n % 10, "мероприятий"
    )


def prose_char_budget(limit, header, footer, tail_count, tail_cost=62):
    """How long the flowing text may be, for telling the AI what to aim at."""
    overhead = visible_length(header) + visible_length(footer)
    return max(0, limit - overhead - tail_cost * max(tail_count, 0))


def comment_char_budget(limit, header, footer, event_count, tail_count=0, tail_cost=62):
    """Rough per-event comment budget, for telling the AI how long to write."""
    if event_count <= 0:
        return 0
    overhead = (
        visible_length(header) + visible_length(footer) + tail_cost * max(tail_count, 0)
    )
    # Linked title + meta line + blank lines ≈ 90 visible chars per event.
    per_event_fixed = 90
    free = limit - overhead - per_event_fixed * event_count
    return max(0, min(DEFAULT_COMMENT_STEPS[0], math.floor(free / event_count)))
