"""Themed digests as Telegram rich messages (Bot API 10.1, June 2026).

A normal channel post is either a photo with a 1024-character caption or 4096
characters of text with no pictures in the middle. That is what forces the
ordinary digest to choose between describing five events and naming ten. A rich
message removes the choice: up to 32768 bytes / 500 blocks, with photo blocks
*inside* the text, so every event can carry its own poster.

Two things differ from :mod:`themes` and are the reason this is a separate
module rather than another ``layout``:

* **The markup is different.** Rich messages take GitHub-flavoured Markdown, not
  MarkdownV2 — no escaping of ``. - ! ( )``, but ``[`` ``]`` ``*`` ``_`` ``\\``
  still have to be neutralised inside text taken from event titles.
* **Media is referenced, not attached.** An image is a ``tg://photo?id=<id>``
  link in the text plus an entry in the message's ``media`` list, so rendering
  produces a text *and* an ordered list of image URLs that the client uploads.

Verified against the live API on 2026-08-18 (channel post, both a public URL and
a multipart ``attach://`` upload).
"""

import re

from . import themes

# Telegram's ceiling for one rich message.
RICH_MESSAGE_MAX_BYTES = 32768
RICH_MESSAGE_MAX_BLOCKS = 500

# What a digest should actually aim at.
DEFAULT_RICH_LIMIT = 1300

DEFAULT_MAX_PHOTOS = 5

PLACE_MAX_CHARS = 0

_GFM_SPECIAL_RE = re.compile(r"([\\`*_\[\]])")

HARD_BREAK = "  \n"


def escape(text):
    """Neutralise GFM markup in text that came from an event, not from us."""
    if not text:
        return ""
    return _GFM_SPECIAL_RE.sub(r"\\\1", str(text))


def link(label, url):
    """``[label](url)`` with the label escaped and the URL left intact."""
    label = escape(label)
    if not url:
        return label
    return f"[{label}]({str(url).replace(' ', '%20')})"


def photo_ref(media_id):
    """The in-text reference that pulls a photo into the message body."""
    return f"![](tg://photo?id={media_id})"


def media_id(index):
    """Media ids are positional (``ev1``, ``ev2``…) — 1-64 chars of ``A-Za-z0-9_-``."""
    return f"ev{index + 1}"


def event_photo_url(event):
    """The event's own poster, or ``""`` — the S3 key in ``image_upload`` is not a URL."""
    for value in (event.get("image_upload"), event.get("image")):
        if isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def visible_length(text):
    """Characters a reader sees: link URLs and photo references are not text."""
    rendered = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text or "")
    rendered = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", rendered)
    rendered = re.sub(r"\\(.)", r"\1", rendered)
    return len(rendered.strip())


def event_line(event, with_place=True):
    """``чт 20 авг, 14:00 · Лендок · бесплатно`` — the non-AI facts, one line."""
    parts = [
        themes.fmt_compact_date(event.get("from_date"), event.get("to_date")),
        themes.event_place_name(event, PLACE_MAX_CHARS) if with_place else "",
        themes.fmt_price(event),
    ]
    return " · ".join(p for p in parts if p)


def event_facts(event):
    """Date, venue and ticket link as separate labelled lines."""
    lines = []
    when = themes.fmt_compact_date(event.get("from_date"), event.get("to_date"))
    if when:
        lines.append(f"📅 {escape(when)}")
    place = themes.event_place_name(event, PLACE_MAX_CHARS)
    if place:
        lines.append(f"📍 {escape(place)}")

    price = themes.fmt_price(event) or "Подробнее"
    url = themes.event_link(event)
    lines.append(f"🎟 {link(price, url)}" if url else f"🎟 {escape(price)}")
    return lines


def render_prose_paragraphs(text, events):
    """AI prose with ``{{id}}`` markers → GFM paragraphs + a photo per paragraph."""
    by_id = {}
    for event in events:
        try:
            by_id[int(event.get("id"))] = event
        except (TypeError, ValueError):
            continue

    paragraphs, photos, used = [], {}, []
    for raw in re.split(r"\n\s*\n", (text or "").strip()):
        if not raw.strip():
            continue

        out, pos, mentioned = [], 0, []
        for match in themes.PROSE_REF_RE.finditer(raw):
            out.append(escape(raw[pos : match.start()]))
            pos = match.end()

            event = by_id.get(int(match.group(1)))
            label = (match.group(2) or "").strip()
            if event is None:
                out.append(escape(label))
                continue

            label = themes.shorten(label or (event.get("title") or ""), 80)
            out.append(link(label, themes.event_link(event)))
            mentioned.append(event)
            if event.get("id") not in used:
                used.append(event.get("id"))
        out.append(escape(raw[pos:]))

        index = len(paragraphs)
        paragraphs.append("".join(out).strip())
        for event in mentioned:
            url = event_photo_url(event)
            if url:
                photos[index] = url
                break

    return paragraphs, photos, used


def build_detailed(
    title, emoji, intro, events, comments, max_photos=DEFAULT_MAX_PHOTOS,
    picks_label="", photos_mode="each",
):
    """Heading, intro, then the described events."""
    heading = f"## {escape(f'{emoji} {title}'.strip())}"
    parts = [heading]
    if intro:
        parts.append(escape(intro))

    if photos_mode == "collage":
        collage_sources = [url for url in (event_photo_url(e) for e in events) if url]
        if collage_sources:
            parts.append(photo_ref(media_id(0)))
        if picks_label:
            parts.append(f"**{escape(picks_label)}**")
        for event in events:
            parts.append(_event_block(event, comments))
        return "\n\n".join(parts), collage_sources

    if picks_label:
        parts.append(f"**{escape(picks_label)}**")

    # Spread photos instead of front-loading them.
    with_photos = [e for e in events if event_photo_url(e)]
    if max_photos and len(with_photos) > max_photos:
        step = len(with_photos) / max_photos
        chosen = {id(with_photos[int(i * step)]) for i in range(max_photos)}
    else:
        chosen = {id(e) for e in with_photos[:max_photos]}

    photos = []
    for event in events:
        url = event_photo_url(event)
        if url and id(event) in chosen:
            parts.append(photo_ref(media_id(len(photos))))
            photos.append(url)

        parts.append(_event_block(event, comments))

    return "\n\n".join(parts), photos


def _event_block(event, comments):
    """One described event: bold title, the AI's lines, then the labelled facts."""
    title = themes.shorten(event.get("title") or "", 80)
    block = [f"**{escape(title)}**"]
    comment = (comments.get(event.get("id")) or "").strip()
    if comment:
        block.append(escape(comment))
    block.extend(event_facts(event))
    return HARD_BREAK.join(block)


def build_prose(
    title, emoji, paragraphs, photos_by_paragraph, intro="",
    max_photos=DEFAULT_MAX_PHOTOS,
):
    """Heading, one-sentence intro, then prose paragraphs with photos between them."""
    parts = [f"## {escape(f'{emoji} {title}'.strip())}"]
    if intro:
        parts.append(f"_{escape(intro)}_")
    photos = []
    for index, paragraph in enumerate(paragraphs):
        url = photos_by_paragraph.get(index)
        if url and len(photos) < max_photos:
            parts.append(photo_ref(media_id(len(photos))))
            photos.append(url)
        parts.append(paragraph)
    return "\n\n".join(p for p in parts if p), photos


def build_by_day(title, emoji, intro, events, photos_mode="collage",
                 max_photos=DEFAULT_MAX_PHOTOS):
    """Day headings, then one line per event — the shape a weekend digest wants."""
    parts = [f"## {escape(f'{emoji} {title}'.strip())}"]
    if intro:
        parts.append(escape(intro))

    photos = []
    if photos_mode == "collage":
        photos = [url for url in (event_photo_url(e) for e in events) if url]
        if photos:
            parts.append(photo_ref(media_id(0)))

    for day, day_events in themes.group_by_day(events):
        lines = [f"**{escape(themes.fmt_day_header(day))}**"]
        for event in day_events:
            head = link(themes.shorten(event.get("title") or "", 60),
                        themes.event_link(event))
            when = event.get("from_date")
            bits = []
            if hasattr(when, "hour") and (when.hour or when.minute):
                bits.append(f"{when.hour:02d}:{when.minute:02d}")
            price = themes.fmt_price(event)
            if price:
                bits.append(price)
            meta = " · ".join(bits)
            lines.append(f"🔹 {head} — {escape(meta)}" if meta else f"🔹 {head}")
        parts.append(HARD_BREAK.join(lines))

    return "\n\n".join(parts), photos


def build_tail(events, label=""):
    """The "also this week" list — one bullet per event, no photos."""
    events = list(events)
    if not events:
        return ""
    lines = [f"**{escape(label)}**"] if label else []
    for event in events:
        head = link(themes.shorten(event.get("title") or "", 60), themes.event_link(event))
        meta = event_line(event, with_place=False)
        lines.append(f"🔹 {head} — {escape(meta)}" if meta else f"🔹 {head}")
    return HARD_BREAK.join(lines)


def join_sections(*sections):
    """Join non-empty sections with a blank line between them."""
    return "\n\n".join(s.strip() for s in sections if s and s.strip())
