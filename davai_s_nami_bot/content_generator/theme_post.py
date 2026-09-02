"""Themed digest posts: selection -> AI text -> budgeted render.

A theme is a row in ``ContentGeneratorFilterSet`` (``filter_type='semantic'``).
Candidates come either from the scored feed or from an embedding match on the
theme text; the venue cap, cooldown and relevance floor exist because a raw
nearest-neighbour list makes a repetitive digest.
"""

import json
import logging
import re
from datetime import datetime, time as dt_time, timedelta, timezone

from . import crud
from . import themes
from . import theme_prompts
from . import themes_rich
from .. import crud as dsn_crud
from .. import utils
from ..pydantic_models import EventRequestParameters
from ..helper.ai_helper import AIHelper
from ..helper.ai.query_analyzer import _resolve_relative_range
from ..helper.dsn_parameters import DSNParameters
from ..helper.embeddings import EmbeddingClient, current_embedding_model_label
from ..scoring import CATEGORY_ID_TO_NAME
from ..settings.settings_loader import settings

log = logging.getLogger(__name__)

MSK_TZ = timezone(timedelta(hours=3))

#: Slack over what the prompt asks for: models overshoot by a few words, and
#: cutting at exactly the asked-for number ends mid-word.
INTRO_SLACK = 80


def _clean_intro(raw, intro_max):
    """Trim an intro to whole sentences rather than mid-word.

    A character cut left posts opening with "...если хочется просто смотреть
    кино, а не…", which reads worse than one sentence fewer.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    limit = int(intro_max) + INTRO_SLACK
    trimmed = themes.trim_sentences(text, limit)
    # A single over-long sentence survives trim_sentences untouched.
    if themes.visible_length(trimmed) > limit:
        return themes.shorten(trimmed, limit)
    return trimmed

#: No count: the web-app list is live, so its size is unknown when rendering.
DEFAULT_FOOTER_LABEL = "Все мероприятия — в приложении"

# Per-theme knobs, overridable from ``ContentGeneratorFilterSet.filter_params``.
DEFAULT_THEME_PARAMS = {
    "semantic_query": "",
    "range": "this_week",
    "max_distance": 0.85,
    "shown": 5,
    "pool": 40,
    "min_events": 3,
    "per_place": 1,
    "per_day": 2,
    "per_category": None,
    "cooldown_selections": 20,
    "post_limit": themes.DEFAULT_POST_LIMIT,
    # detailed | compact | by_day | prose
    "layout": "detailed",
    # Extra events named as one-liners after the described ones.
    "tail": 0,
    "tail_label": "\u0410 \u0435\u0449\u0451 \u043d\u0430 \u043d\u0435\u0434\u0435\u043b\u0435:",
    # "button" costs no characters: Telegram counts only the message text.
    "footer_style": "link",
    # "save" needs a `/start fav_<id>` handler bot-side.
    "event_buttons": "none",
    # plain | rich (Bot API 10.1: photos inside the text, 32768-byte ceiling)
    "format": "plain",
    "rich_limit": themes_rich.DEFAULT_RICH_LIMIT,
    "max_photos": themes_rich.DEFAULT_MAX_PHOTOS,
    # collage | each | none
    "photos": "collage",
    "picks_label": "\u0421\u043e\u0432\u0435\u0442\u0443\u044e \u0441\u0445\u043e\u0434\u0438\u0442\u044c:",
    # 0 = derive from the remaining budget.
    "comment_chars": 0,
    "intro_chars": 260,
    "paragraph_max": 320,
    # feed = scored/diversified, no embedding. semantic = embedding match.
    "selection": "semantic",
    "require_start_in_window": True,
    "max_duration_days": 0,
    "exclude_category_ids": [],
    "location": "",
    "location_scope": "venue",
    # Publication weekdays: [3, 4] / "3-4" / "0,2,4" / None = any.
    "weekdays": None,
    "min_lead_days": 1,
    # filter = live web-app list (no bot handler). selection = frozen pool.
    "footer_link": "filter",
    "footer_label": "",
    "emoji": "\u2728",
    "category_ids": None,
    "price_max": None,
    "free_only": False,
}


def _theme_params(filter_set):
    """Merge a filter set's stored params over the defaults."""
    raw = filter_set.get("filter_params")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            log.warning(
                f"Theme {filter_set.get('id')}: filter_params is not valid JSON, using defaults"
            )
            raw = {}
    params = dict(DEFAULT_THEME_PARAMS)
    params.update(raw or {})
    if not params["semantic_query"]:
        params["semantic_query"] = (
            filter_set.get("description") or filter_set.get("name") or ""
        ).strip()
    return params


_NEXT_DAYS_RE = re.compile(r"^next_(\d{1,2})_days$")

WEEKEND_RANGES = frozenset({"this_weekend", "next_weekend"})

# Thursday and Friday: the weekend is being planned. Mon=0 … Sun=6.
WEEKEND_PLANNING_WEEKDAYS = frozenset({3, 4})


def is_weekend_theme(filter_set):
    """True if the theme's date window targets the weekend."""
    return _theme_params(filter_set)["range"] in WEEKEND_RANGES


def parse_weekdays(value):
    """Weekday restriction -> frozenset of 0..6 (Mon=0), or None for "any day".

    Accepts a list (``[3, 4]``), a range (``"3-4"``), a comma list (``"0,2,4"``)
    and ``"*"``/``None``/``""`` for no restriction. Pure — unit-tested.
    """
    if value is None or value == "" or value == "*":
        return None
    if isinstance(value, int):
        value = [value]
    if isinstance(value, str):
        parts = []
        for chunk in value.replace(" ", "").split(","):
            if not chunk:
                continue
            if "-" in chunk[1:]:
                lo, _, hi = chunk.partition("-")
                parts.extend(range(int(lo), int(hi) + 1))
            else:
                parts.append(int(chunk))
        value = parts
    days = frozenset(int(d) % 7 for d in value)
    return days or None


def theme_weekdays(filter_set):
    """Days a theme may be published on, or None for any day.

    A weekend theme defaults to Thursday/Friday: a digest of the coming weekend
    is planning material, and on Tuesday it is four days early. An explicit
    ``weekdays`` in the theme's params overrides that.
    """
    params = _theme_params(filter_set)
    explicit = parse_weekdays(params.get("weekdays"))
    if explicit is not None:
        return explicit
    if params["range"] in WEEKEND_RANGES:
        return WEEKEND_PLANNING_WEEKDAYS
    return None


def runs_on_weekday(filter_set, weekday):
    """True if the theme is allowed to be published on ``weekday``."""
    days = theme_weekdays(filter_set)
    return days is None or weekday in days


def slot_after_last_event(
    day, last_event_at, offset_hours, fallback, latest, tzinfo
):
    """Publication time for ``day``: the day's last event post plus a gap.

    Individual events still post directly to the channel on their own schedule
    (four weekday slots, three at weekends), so a digest dropped into the middle
    of that stream competes with it. Landing after the day's last event keeps one
    themed post per day out of the way, and it tracks the real schedule — the
    last slot isn't the same every day.

    ``latest`` caps the result inside the same evening: a late last event must not
    push the digest past midnight (or into the small hours of the next day).
    ``fallback`` is used when the day has no event posts at all — a quiet day
    still gets its digest.

    Pure — unit-tested.
    """
    if last_event_at is None:
        return datetime.combine(day, fallback, tzinfo=tzinfo)

    local = last_event_at.astimezone(tzinfo)
    slot = local + timedelta(hours=offset_hours)

    cap = datetime.combine(day, latest, tzinfo=tzinfo)
    if slot > cap:
        return cap
    return slot


def planning_slots(now, days_ahead, resolve_time, lead_minutes=5, max_days=14):
    """The next ``days_ahead`` publication datetimes, skipping slots already past."""
    slots = []
    day = now.date()
    cutoff = now + timedelta(minutes=lead_minutes)
    wanted = max(0, int(days_ahead))
    for _ in range(max_days):
        if len(slots) >= wanted:
            break
        slot = resolve_time(day)
        if slot is not None and slot > cutoff:
            slots.append(slot)
        day += timedelta(days=1)
    return slots


def pick_theme(filter_sets, recent_filter_ids, weekday=None, exclude_ids=()):
    """Least-recently-posted active theme."""
    if not filter_sets:
        return None

    # Without this a two-day plan runs the same theme twice whenever the
    # narrowed pool has only one member.
    excluded = set(exclude_ids or ())
    candidates = [fs for fs in filter_sets if fs["id"] not in excluded] or filter_sets

    if weekday is not None:
        candidates = [fs for fs in candidates if runs_on_weekday(fs, weekday)]
        if not candidates:
            return None
        if weekday in WEEKEND_PLANNING_WEEKDAYS:
            weekend = [fs for fs in candidates if is_weekend_theme(fs)]
            if weekend:
                candidates = weekend

    def staleness(fs):
        try:
            return recent_filter_ids.index(fs["id"])
        except ValueError:
            return len(recent_filter_ids) + fs["id"] % 1000

    return max(candidates, key=staleness)


def _parse_dt(value):
    """ISO string (as returned by the vector search) → MSK datetime."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(MSK_TZ)
    return value


def _event_image_url(event):
    """First downloadable image URL of an event, or ``""``."""
    for value in (event.get("image_upload"), event.get("image")):
        if isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def _normalize_event_dates(events):
    """Event dates → MSK datetimes, which every ordering/render helper expects."""
    for event in events:
        event["from_date"] = _parse_dt(event.get("from_date"))
        event["to_date"] = _parse_dt(event.get("to_date"))
    return events


def _day_bounds(date_from, date_to):
    """Whole-day MSK bounds for a (date, date) pair, matching semantic search."""
    dt_from = (
        datetime.combine(date_from, datetime.min.time(), tzinfo=MSK_TZ)
        if date_from
        else None
    )
    dt_to = (
        datetime.combine(date_to, datetime.max.time(), tzinfo=MSK_TZ)
        if date_to
        else None
    )
    return dt_from, dt_to


def window_for(params, target_date):
    """Event date window for a theme published on ``target_date``.

    ``min_lead_days`` pushes the start forward: a digest that goes out in the
    evening must not list a lecture that started at 15:00 the same day, so by
    default the window opens tomorrow.
    """
    raw_range = str(params["range"]).lower()

    horizon = _NEXT_DAYS_RE.match(raw_range)
    if horizon:
        date_from = target_date
        date_to = target_date + timedelta(days=int(horizon.group(1)))
    else:
        date_from, date_to = _resolve_relative_range(raw_range, target_date)

    lead = int(params.get("min_lead_days") or 0)
    if lead > 0:
        earliest = target_date + timedelta(days=lead)
        if date_from is None or date_from < earliest:
            date_from = earliest
    if date_from is not None and date_to is not None and date_from > date_to:
        log.info(
            f"Theme window for {target_date} is empty: min_lead_days={lead} "
            f"pushes the start past {date_to}"
        )
    return date_from, date_to


def _apply_window_rules(candidates, params, date_from, date_to):
    """Trim candidates to what actually *happens* in the window."""
    candidates = themes.drop_categories(candidates, params.get("exclude_category_ids"))
    if params.get("require_start_in_window"):
        candidates = themes.keep_starting_within(candidates, date_from, date_to)
    return themes.drop_long_runners(candidates, params.get("max_duration_days"))


def select_feed_events(params, *, recent_ids=None, today=None):
    """Pick events for a broad window from the scored, diversified feed."""
    today = today or datetime.now(MSK_TZ).date()
    date_from, date_to = window_for(params, today)
    dt_from, dt_to = _day_bounds(date_from, date_to)

    request = EventRequestParameters(
        date_from=dt_from or datetime.now(MSK_TZ),
        date_to=dt_to,
        category=params.get("category_ids") or None,
        place=_resolve_place_ids(params),
        price_max=params.get("price_max"),
        limit=int(params["pool"]),
    )
    found = dsn_crud.get_diverse_event_feed(
        request,
        per_category=params.get("per_category"),
        per_day=params.get("per_day"),
    )
    candidates = _normalize_event_dates(found["events"])

    candidates = _apply_window_rules(candidates, params, date_from, date_to)
    candidates = themes.drop_recent(candidates, recent_ids or ())
    candidates = themes.cap_per_place(candidates, params.get("per_place"))

    shown = candidates[: int(params["shown"])]
    return shown, candidates


def _resolve_place_ids(params):
    """Place ids for the theme's ``location``, or None when it has none.

    Degrades to None (no place filter) rather than to an empty list: an empty
    list would filter everything out and silently produce an empty theme.
    """
    phrase = (params.get("location") or "").strip()
    if not phrase:
        return None
    try:
        ids = dsn_crud.resolve_location_place_ids(
            phrase,
            scope=str(params.get("location_scope") or "venue"),
            adjacency=getattr(settings, "metro_adjacency", {}),
        )
    except Exception as e:
        log.warning(f"Theme location {phrase!r} could not be resolved: {e}")
        return None
    if not ids:
        log.info(f"Theme location {phrase!r} matched no places; using text match only")
        return None
    return ids


def select_theme_events(params, *, recent_ids=None, today=None):
    """Run the theme's semantic query and reduce it to a pool and a shown set."""
    today = today or datetime.now(MSK_TZ).date()
    date_from, date_to = window_for(params, today)
    dt_from, dt_to = _day_bounds(date_from, date_to)

    vector = EmbeddingClient().embed_batch([params["semantic_query"]])[0]

    found = dsn_crud.search_events_by_embedding(
        vector,
        current_embedding_model_label(),
        date_from=dt_from,
        date_to=dt_to,
        category_ids=params.get("category_ids"),
        price_max=params.get("price_max"),
        free_only=bool(params.get("free_only")),
        limit=int(params["pool"]),
        max_distance=params.get("max_distance"),
        place_ids=_resolve_place_ids(params),
        location_text=(params.get("location") or "").strip() or None,
        rerank=True,
    )
    candidates = _normalize_event_dates(found["events"])

    candidates = _apply_window_rules(candidates, params, date_from, date_to)
    candidates = themes.drop_recent(candidates, recent_ids or ())
    candidates = themes.cap_per_place(candidates, params.get("per_place"))

    # `_diverse_order`, not `select_diverse_events`: the latter re-sorts its
    # slice by score, throwing away the theme's own ranking.
    pool = dsn_crud._diverse_order(
        candidates,
        per_category=params.get("per_category"),
        per_day=params.get("per_day"),
    )
    shown = pool[: int(params["shown"])]
    return shown, pool


# --- AI comments ------------------------------------------------------------

def _event_payload(events):
    """What the model is told about each event. Internal fields stay out."""
    return [
        {
            "id": e.get("id"),
            "title": e.get("title"),
            "when": themes.fmt_compact_date(e.get("from_date"), e.get("to_date")),
            "place": themes.event_place_name(e),
            "price": themes.fmt_price(e),
            "description": themes.shorten(
                (e.get("prepared_text") or e.get("full_text") or "").strip(), 600
            ),
        }
        for e in events
    ]


_SALVAGE_COMMENT_RE = re.compile(
    r'\{\s*"id"\s*:\s*(\d+)\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
)
_SALVAGE_INTRO_RE = re.compile(r'"intro"\s*:\s*"((?:[^"\\]|\\.)*)"')
_SALVAGE_TEXT_RE = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _salvage_ai_json(text):
    """Recover whole entries from a reply that is valid JSON only up to a point."""
    comments = []
    for match in _SALVAGE_COMMENT_RE.finditer(text):
        try:
            comments.append(
                {"id": int(match.group(1)), "text": json.loads(f'"{match.group(2)}"')}
            )
        except (ValueError, json.JSONDecodeError):
            continue

    intro_match = _SALVAGE_INTRO_RE.search(text)
    intro = ""
    if intro_match:
        try:
            intro = json.loads(f'"{intro_match.group(1)}"')
        except (ValueError, json.JSONDecodeError):
            intro = ""

    prose = ""
    prose_match = _SALVAGE_TEXT_RE.search(text)
    if prose_match and not comments:
        try:
            prose = json.loads(f'"{prose_match.group(1)}"')
        except (ValueError, json.JSONDecodeError):
            prose = ""
    return {"intro": intro, "comments": comments, "text": prose}


def _parse_ai_json(raw):
    """Extract the JSON object from a model reply, tolerating fences and cut-offs."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass

    salvaged = _salvage_ai_json(text)
    if salvaged["comments"] or salvaged["intro"] or salvaged["text"]:
        log.warning(
            f"Theme post: AI reply was not valid JSON, salvaged "
            f"{len(salvaged['comments'])} comment(s)"
        )
        return salvaged

    log.warning("Theme post: could not parse AI JSON reply")
    return {}


def _ask_ai(prompt_body, system_message):
    """One call to the configured model — ``""`` on any failure."""
    model_name = (settings.content_generator or {}).get(
        "ai_model_name"
    ) or DSNParameters().site_parameters("ai_model", last=1)
    try:
        return AIHelper(model_name).generate_text(
            system_message,
            prompt_body,
            temperature=0.7,
            # Reasoning models spend output tokens before emitting anything:
            # at 1500 Gemini hit finish_reason=length and returned broken JSON.
            max_tokens=4000,
        )
    except Exception as e:
        log.error(f"Theme post: AI call failed, rendering without: {e}")
        return ""


def _intro_max(params):
    """Character target for the intro, from the theme's ``intro_chars``."""
    return int((params or {}).get("intro_chars") or 260)


def generate_comments(theme_title, params, events, comment_max, also=()):
    """``(intro, {event_id: comment})`` from the AI — empty on any failure."""
    if not events:
        return "", {}

    system, editorial = theme_prompts.resolve_prompts(DSNParameters())
    raw = _ask_ai(
        editorial
        + theme_prompts.comments_contract(
            theme_title, _event_payload(events), comment_max,
            intro_max=_intro_max(params), also=also,
        ),
        system,
    )

    data = _parse_ai_json(raw)
    intro = _clean_intro(data.get("intro"), _intro_max(params))

    comments = {}
    for item in data.get("comments") or []:
        try:
            event_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        text = (item.get("text") or "").strip()
        if text:
            comments[event_id] = text
    return intro, comments


def generate_prose(theme_title, params, events, prose_max, paragraph_max=320, also=()):
    """``(intro, [paragraph, ...])`` from the AI — empty on any failure."""
    if not events:
        return "", []

    system, editorial = theme_prompts.resolve_prompts(DSNParameters())
    raw = _ask_ai(
        editorial
        + theme_prompts.prose_contract(
            theme_title, _event_payload(events), prose_max, paragraph_max,
            intro_max=_intro_max(params), also=also,
        ),
        system,
    )

    data = _parse_ai_json(raw)
    intro = _clean_intro(data.get("intro"), _intro_max(params))
    paragraphs = [
        str(p).strip() for p in (data.get("paragraphs") or []) if str(p).strip()
    ]
    if not paragraphs and data.get("text"):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", data["text"]) if p.strip()]
    return intro, paragraphs


def generate_intro_only(theme_title, params, events, also=()):
    """Just the intro, for compact layouts that have no per-event comments."""
    if not events:
        return "", {}

    system, editorial = theme_prompts.resolve_prompts(DSNParameters())
    titles = "\n".join(f"- {e.get('title')}" for e in events)
    raw = _ask_ai(
        editorial
        + f"""

Тема подборки: «{theme_title}». Мероприятия:
{titles}
{theme_prompts._also_block(also)}
Верни СТРОГО JSON: {{"intro": "..."}} — только вступление, до {_intro_max(params)} символов,
по правилам выше. Не используй слова из заголовка «{theme_title}» и однокоренные с ними.""",
        system,
    )
    return _clean_intro(_parse_ai_json(raw).get("intro"), _intro_max(params)), {}


# --- Orchestration ----------------------------------------------------------

def _bot_url():
    return (settings.content_generator or {}).get("bot_url") or ""


def _bot_favourite_url(event_id):
    """Deep link that saves one event to the reader's favourites in the bot."""
    bot_url = _bot_url()
    if not bot_url:
        return ""
    return f"{bot_url.rstrip('/')}?start=fav_{event_id}"


def event_save_buttons(events, max_buttons=5, label_chars=30):
    """One "save to favourites" button per event, or ``[]``."""
    buttons = []
    for event in events[:max_buttons]:
        url = _bot_favourite_url(event.get("id"))
        if not url:
            continue
        buttons.append(
            {"text": f"⭐ {button_label(event, label_chars)}", "url": url}
        )
    return buttons


_QUOTED_NAME_RE = re.compile(r"«([^»]{2,})»")
_LEADING_JUNK_RE = re.compile(r"^[^\w(«]+")


def button_label(event, label_chars=30):
    """Shortest recognisable name of an event, for a button."""
    title = _LEADING_JUNK_RE.sub("", event.get("title") or "").strip()
    quoted = _QUOTED_NAME_RE.search(title)
    if quoted and len(quoted.group(1)) >= 4:
        title = quoted.group(1)
    return themes.shorten(title, label_chars)


def _bot_selection_url(selection_id):
    """Deep link to the frozen selection in the bot, or "" if not configured."""
    bot_url = _bot_url()
    if not bot_url:
        return ""
    return f"{bot_url.rstrip('/')}?start=sel_{selection_id}"


def _theme_category_filter(params):
    """Category section for the web-app link, honouring `exclude_category_ids`."""
    include = [int(c) for c in (params.get("category_ids") or []) if c]
    exclude = {int(c) for c in (params.get("exclude_category_ids") or []) if c}

    if include:
        return themes.webapp_category_filter([c for c in include if c not in exclude])
    if exclude:
        return themes.webapp_category_filter(
            [c for c in sorted(CATEGORY_ID_TO_NAME) if c not in exclude]
        )
    return ""


def theme_webapp_url(params, date_from, date_to):
    """Web-app link reproducing the theme's own filters (dates, categories, price)."""
    return themes.webapp_link(
        _bot_url(),
        themes.webapp_date_filter(date_from, date_to),
        _theme_category_filter(params),
        themes.webapp_price_filter(
            params.get("price_max"), bool(params.get("free_only"))
        ),
    )


def render_rich_post(filter_set, params, layout, shown, tail_events):
    """Build a rich message: ``(markdown, photo_urls, kept_events)``."""
    title, emoji = filter_set["name"], params["emoji"]
    limit = int(params.get("rich_limit") or themes_rich.DEFAULT_RICH_LIMIT)
    max_photos = int(params.get("max_photos") or themes_rich.DEFAULT_MAX_PHOTOS)

    if layout == themes.LAYOUT_PROSE:
        intro, raw_paragraphs = generate_prose(
            title, params, shown, limit, int(params.get("paragraph_max") or 320)
        )
        paragraphs, photos_by_paragraph, used_ids = (
            themes_rich.render_prose_paragraphs("\n\n".join(raw_paragraphs), shown)
        )
        if paragraphs:
            body, photos = themes_rich.build_prose(
                title, emoji, paragraphs, photos_by_paragraph, intro=intro,
                max_photos=max_photos,
            )
            kept = [e for e in shown if e.get("id") in set(used_ids)]
        else:
            log.warning("Theme post: empty prose, falling back to the detailed layout")
            layout = themes.LAYOUT_DETAILED

    if layout == themes.LAYOUT_BY_DAY:
        intro, _ = generate_intro_only(title, params, shown, also=tail_events)
        body, photos = themes_rich.build_by_day(
            title, emoji, intro, shown,
            photos_mode=str(params.get("photos") or "collage").lower(),
            max_photos=max_photos,
        )
        kept = list(shown)

    if layout not in (themes.LAYOUT_PROSE, themes.LAYOUT_BY_DAY):
        comment_max = int(params.get("comment_chars") or 0) or min(
            max(int(limit / max(len(shown), 1)) - 90, 60),
            themes.DEFAULT_COMMENT_STEPS[0],
        )
        intro, comments = generate_comments(title, params, shown, comment_max)
        body, photos = themes_rich.build_detailed(
            title, emoji, intro, shown, comments,
            max_photos=max_photos,
            picks_label=params.get("picks_label") or "",
            photos_mode=str(params.get("photos") or "each").lower(),
        )
        kept = list(shown)

    tail = themes_rich.build_tail(tail_events, params.get("tail_label") or "")
    text = themes_rich.join_sections(body, tail)
    return text, photos, kept + list(tail_events)


def build_theme_post(
    filter_set_id=None, dry_run=False, target_date=None, exclude_filter_ids=()
):
    """Build (and normally persist) one themed digest post."""
    target_date = target_date or datetime.now(MSK_TZ).date()

    if filter_set_id:
        filter_set = crud.get_filter_set_by_id(filter_set_id)
    else:
        active = crud.get_active_filter_sets(filter_type="semantic")
        if not active:
            return {"status": "no_active_themes"}
        filter_set = pick_theme(
            active,
            crud.get_recent_selection_filter_ids(),
            weekday=target_date.weekday(),
            exclude_ids=exclude_filter_ids,
        )
        if filter_set is None:
            # Every active theme is restricted to other weekdays.
            return {"status": "no_theme_for_day", "weekday": target_date.weekday()}

    params = _theme_params(filter_set)
    if not params["semantic_query"]:
        return {"status": "empty_theme", "filter_set_id": filter_set["id"]}

    recent_ids = crud.get_recently_used_event_ids(
        last_selections=int(params["cooldown_selections"])
    )
    select = (
        select_feed_events
        if str(params.get("selection") or "semantic").lower() == "feed"
        else select_theme_events
    )
    shown, pool = select(params, recent_ids=recent_ids, today=target_date)

    tail_count = max(int(params.get("tail") or 0), 0)
    tail_events = pool[len(shown) : len(shown) + tail_count] if tail_count else []

    # Same window the selection used — the footer link must filter identically.
    date_from, date_to = window_for(params, target_date)

    if len(shown) < int(params["min_events"]):
        log.info(
            f"Theme {filter_set['name']!r}: only {len(shown)} events "
            f"(min {params['min_events']}), skipping"
        )
        return {
            "status": "not_enough_events",
            "filter_set_id": filter_set["id"],
            "theme": filter_set["name"],
            "found": len(shown),
        }

    selection_id = None
    if not dry_run:
        selection = crud.create_event_selection(
            {
                "filter_set_id": filter_set["id"],
                "name": filter_set["name"],
                "status": "draft",
                "generation_settings": json.dumps(
                    {**params, "shown_ids": [e["id"] for e in shown]},
                    ensure_ascii=False,
                    default=str,
                ),
            }
        )
        selection_id = selection["id"]
        crud.add_selected_events(selection, pool)

    # On a dry run there is no selection id, but the footer still has to take
    # its share of the budget or the preview would look roomier than reality.
    footer_label = params.get("footer_label") or DEFAULT_FOOTER_LABEL
    if str(params.get("footer_link") or "filter").lower() == "selection":
        footer_url = _bot_selection_url(selection_id if selection_id else 0)
        rest = len(pool) - len(shown) - len(tail_events)
        footer = themes.build_footer(footer_url, rest)
        footer_label = themes.footer_label(rest) or footer_label
    else:
        footer_url = theme_webapp_url(params, date_from, date_to)
        footer = themes.build_footer(footer_url, label=footer_label)

    # A button costs no characters: Telegram counts the message text only.
    button = None
    if footer_url and str(params.get("footer_style") or "link").lower() == "button":
        button = {"text": footer_label, "url": footer_url}
        footer = ""

    layout = str(params.get("layout") or themes.LAYOUT_DETAILED).lower()
    header_probe = themes.build_header(params["emoji"], filter_set["name"], "")
    post_format = str(params.get("format") or "plain").lower()

    if post_format == "rich":
        text, photos, kept = render_rich_post(
            filter_set, params, layout, shown, tail_events
        )
        buttons = _post_buttons(button, params, shown, kept)
        return _finish_theme_post(
            result_base={
                "status": "ok",
                "filter_set_id": filter_set["id"],
                "theme": filter_set["name"],
                "content": text,
                "buttons": buttons,
                "format": "rich",
                "length": themes_rich.visible_length(text),
                "raw_length": len(text),
                "shown_ids": [e["id"] for e in kept],
                "pool_size": len(pool),
                "event_selection_id": selection_id,
            },
            filter_set=filter_set,
            params=params,
            buttons=buttons,
            media=photos,
            selection_id=selection_id,
            dry_run=dry_run,
        )

    prose = ""
    if layout == themes.LAYOUT_PROSE:
        prose_max = themes.prose_char_budget(
            int(params["post_limit"]), header_probe, footer, len(tail_events)
        )
        prose_intro, raw_paragraphs = generate_prose(
            filter_set["name"], params, shown, max(prose_max, 200),
            int(params.get("paragraph_max") or 320),
        )
        prose, _ = themes.render_prose("\n\n".join(raw_paragraphs), shown)
        if not prose:
            log.warning("Theme post: empty prose, falling back to the detailed layout")
            layout = themes.LAYOUT_DETAILED

    if layout == themes.LAYOUT_PROSE:
        intro, comments = prose_intro, {}
    elif layout != themes.LAYOUT_DETAILED:
        intro, comments = generate_intro_only(filter_set["name"], params, shown)
    else:
        comment_max = int(params.get("comment_chars") or 0) or themes.comment_char_budget(
            int(params["post_limit"]),
            header_probe,
            footer,
            len(shown),
            tail_count=len(tail_events),
        )
        intro, comments = generate_comments(
            filter_set["name"], params, shown, max(comment_max, 40),
            also=tail_events,
        )

    header = themes.build_header(params["emoji"], filter_set["name"], intro)
    text, kept = themes.assemble_post(
        header,
        [] if layout == themes.LAYOUT_PROSE else shown,
        comments,
        footer,
        limit=int(params["post_limit"]),
        min_events=int(params["min_events"]),
        layout=layout,
        tail_events=tail_events,
        tail_label=params.get("tail_label") or "",
        prose=prose,
    )
    if layout == themes.LAYOUT_PROSE:
        # assemble_post cannot know which events the prose named.
        kept = [e for e in shown if themes.is_mentioned(e, text)] + [
            e for e in tail_events if themes.is_mentioned(e, text)
        ]

    collage = None
    if not dry_run:
        image_urls = [url for url in (_event_image_url(e) for e in kept) if url]
        if image_urls:
            try:
                collage = utils.create_collage_and_upload(image_urls)
            except Exception as e:
                log.warning(f"Theme post: collage failed, continuing without: {e}")

    buttons = _post_buttons(button, params, shown, kept)
    return _finish_theme_post(
        result_base={
            "status": "ok",
            "filter_set_id": filter_set["id"],
            "theme": filter_set["name"],
            "content": text,
            "buttons": buttons,
            "format": "plain",
            # raw_length is what we actually send; length is what Telegram counts.
            "length": themes.visible_length(text),
            "raw_length": len(text),
            "shown_ids": [e["id"] for e in kept],
            "pool_size": len(pool),
            "event_selection_id": selection_id,
        },
        filter_set=filter_set,
        params=params,
        buttons=buttons,
        media=[collage["url"]] if collage else [],
        selection_id=selection_id,
        dry_run=dry_run,
    )


def _post_buttons(footer_button, params, shown, kept):
    """The post's inline keyboard: the "everything else" link plus per-event saves."""
    buttons = [footer_button] if footer_button else []
    if str(params.get("event_buttons") or "none").lower() == "save":
        shown_ids = {e.get("id") for e in shown}
        described = [e for e in kept if e.get("id") in shown_ids]
        buttons.extend(event_save_buttons(described))
    return buttons


def _finish_theme_post(
    *, result_base, filter_set, params, buttons, media, selection_id, dry_run
):
    """Persist a built post (draft + media + what it ended up showing)."""
    result = dict(result_base)
    if media:
        result["image"] = media[0]
        result["media"] = media
    if dry_run:
        return result

    post = crud.create_generated_post(
        {
            "title": themes.shorten(filter_set["name"], 295),
            "content": result["content"],
            "status": "draft",
            "event_selection_id": selection_id,
            "media_files": json.dumps(media or []),
        }
    )
    result["id"] = post["id"]

    # Posting reads these back from here, so the generated post needs no new column.
    crud.update_event_selection(
        selection_id,
        {
            "generation_settings": json.dumps(
                {
                    **params,
                    "shown_ids": result["shown_ids"],
                    "buttons": buttons,
                    "format": result.get("format", "plain"),
                },
                ensure_ascii=False,
                default=str,
            )
        },
    )
    return result
