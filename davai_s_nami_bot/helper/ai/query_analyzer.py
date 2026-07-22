# -*- coding: utf-8 -*-
"""Natural-language search-query analyzer.

Turns a free-text user message ("джазовый концерт в выходные") into a structured
search intent: a clean semantic query for the embedding model plus hard filters
(dates, categories, price) that the LLM cannot express through similarity alone.

The model does NOT know the current date, so the caller passes today's date and
weekday and we ask it to resolve relative phrases ("в выходные", "завтра", "на
следующей неделе") into concrete ISO dates. Everything the model returns is
validated/normalized in Python before it reaches the DB query.
"""

import datetime
import json
import logging
import os

from openai import OpenAI, OpenAIError

from ...scoring import CATEGORY_ID_TO_NAME

log = logging.getLogger(__name__)

# Reverse map: category name (lower-cased) → main_category_id.
_NAME_TO_CATEGORY_ID = {name.lower(): cid for cid, name in CATEGORY_ID_TO_NAME.items()}

_CATEGORY_NAMES = list(CATEGORY_ID_TO_NAME.values())

# Shape we ask the model to return. Kept in the prompt as a literal example.
_RESULT_SCHEMA = {
    "is_event_search": True,
    "semantic_query": "<очищенный запрос для семантического поиска>",
    "categories": ["<название категории>"],
    "relative_range": "<today|tomorrow|this_weekend|next_weekend|this_week|next_week|none>",
    "date_from": "<YYYY-MM-DD или null>",
    "date_to": "<YYYY-MM-DD или null>",
    "price_max": "<число или null>",
    "free_only": False,
    "keywords": ["<ключевое слово>"],
    "reply": "<короткий дружелюбный ответ, только если is_event_search=false>",
}

_RELATIVE_RANGES = frozenset(
    {"today", "tomorrow", "this_weekend", "next_weekend", "this_week", "next_week"}
)

_SYSTEM_FALLBACK = (
    "Ты — анализатор поисковых запросов для афиши мероприятий Санкт-Петербурга. "
    "Пользователь пишет свободный текст, ты превращаешь его в структуру для "
    "семантического поиска. Возвращай только JSON, без пояснений."
)

_REPLY_SYSTEM = (
    "Ты — дружелюбный помощник телеграм-афиши мероприятий Санкт-Петербурга для "
    "молодой аудитории. Пиши живо, тепло и по-русски, коротко и по теме афиши. "
    "Отвечай обычным текстом, без Markdown."
)

# --- Providers --------------------------------------------------------------
# Both reachable through the OpenAI SDK; Gemini via its OpenAI-compatible endpoint.

PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"

PROVIDER_CONFIGS = {
    PROVIDER_OPENAI: {
        "model": "gpt-4o-mini",
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
    },
    PROVIDER_GEMINI: {
        "model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API",
    },
}


def _settings_query_analyzer():
    """``features.query_analyzer`` from settings.json, or {} if unavailable."""
    try:
        from ...settings.settings_loader import settings

        return getattr(settings, "query_analyzer", {}) or {}
    except Exception:
        return {}


# Keep follow-up context bounded so a long chat can't blow up the token budget.
_MAX_HISTORY_TURNS = 6


def _build_user_prompt(message, today, weekday_ru, has_history=False):
    categories = ", ".join(_CATEGORY_NAMES)
    schema = json.dumps(_RESULT_SCHEMA, ensure_ascii=False, indent=2)
    context_note = (
        "Выше — предыдущие сообщения этого же диалога. Если текущий запрос — "
        'уточнение к ним (например «подешевле», «а в субботу?», «только '
        'бесплатные»), пойми из контекста, о чём шла речь, и дополни/измени '
        "фильтры соответственно.\n"
        "ВАЖНО: если пользователь просто просит другие/следующие варианты того "
        'же («а ещё?», «что-то другое», «ещё варианты», «покажи ещё»), СОХРАНИ '
        "ранее понятые фильтры без изменений (тот же relative_range/даты, ту же "
        "категорию, ту же цену) — НЕ расширяй окно дат и НЕ сбрасывай категорию. "
        "Меняй фильтр только если пользователь явно об этом просит (например «а "
        'на следующей неделе», «подешевле»). Если это новый самостоятельный '
        "запрос — игнорируй предыдущие сообщения.\n\n"
        if has_history
        else ""
    )
    return f"""{context_note}Запрос пользователя: "{message}"

Сегодня {today.isoformat()} ({weekday_ru}). Используй эту дату, чтобы превратить
относительные выражения ("сегодня", "завтра", "в выходные", "на этой неделе",
"на следующей неделе") в конкретные даты в формате YYYY-MM-DD.

Верни строго JSON такой структуры:
{schema}

Правила:
- is_event_search: false, если это не запрос на поиск мероприятия (приветствие,
  болтовня, бессмыслица). В этом случае остальные поля можно оставить пустыми,
  но заполни поле reply.
- reply: заполняй ТОЛЬКО когда is_event_search=false — короткий (1-2 фразы),
  живой, дружелюбный ответ на реплику пользователя, по теме афиши/мероприятий,
  можно с 1 эмодзи, без Markdown. Не уводи разговор далеко от темы. Когда
  is_event_search=true — оставь reply пустым (подводку к найденному система
  сгенерит сама).
- semantic_query: суть запроса для векторного поиска. Убери служебные слова про
  дату/цену/город, оставь тему и характер мероприятия. Можно слегка расширить
  синонимами ("джазовый концерт" → "джазовый концерт живая музыка").
- categories: ноль или несколько названий ТОЛЬКО из этого списка: {categories}.
  Если категория не очевидна — верни пустой список.
- relative_range: если в запросе есть относительное выражение времени, верни
  ОДИН из токенов: "today" (сегодня), "tomorrow" (завтра), "this_weekend"
  (в выходные / на этих выходных), "next_weekend" (в следующие выходные),
  "this_week" (на этой неделе), "next_week" (на следующей неделе). Конкретные
  даты при этом НЕ вычисляй — их посчитает система. Если время указано явной
  датой ("31 июля", "в августе") или не указано вовсе — верни "none".
- date_from / date_to: заполняй ТОЛЬКО когда relative_range = "none" и в запросе
  явные даты (YYYY-MM-DD); иначе оставь null.
- price_max: верхний предел цены в рублях, если упомянут ("до 1000 рублей"),
  иначе null. free_only: true только если просят бесплатное.
- keywords: важные слова из запроса (тема, жанр), которые стоит учесть.
"""


class QueryAnalyzer:
    """Parse a free-text query into a structured, validated search intent."""

    def __init__(self, dsn_param, provider=None, model=None):
        sett = _settings_query_analyzer()
        # Resolution order: explicit arg → settings.json → env → default.
        provider = (
            provider
            or sett.get("provider")
            or os.environ.get("QUERY_ANALYZER_PROVIDER")
            or PROVIDER_OPENAI
        ).lower()
        if provider not in PROVIDER_CONFIGS:
            raise ValueError(
                f"Unknown query_analyzer provider {provider!r}, "
                f"expected one of {list(PROVIDER_CONFIGS)}"
            )
        cfg = PROVIDER_CONFIGS[provider]
        self.provider = provider

        api_key = os.environ.get(cfg["api_key_env"])
        client_kwargs = {"api_key": api_key}
        if cfg["base_url"]:
            client_kwargs["base_url"] = cfg["base_url"]
        self.client = OpenAI(**client_kwargs)

        # System prompt stays a Redis param (Django-editable); falls back to the
        # hardcoded default when nothing is seeded.
        self.system_message = (
            dsn_param.site_parameters("query_analyzer_system_message", last=1)
            or _SYSTEM_FALLBACK
        )
        # Model: explicit arg → settings.json → chosen provider's default. The
        # settings model only applies to its own provider, so overriding the
        # provider (via arg/env) can't accidentally pin another provider's model.
        sett_provider = (sett.get("provider") or "").lower()
        sett_model = sett.get("model") if sett_provider in ("", provider) else None
        self.model = model or sett_model or cfg["model"]

    def analyze(self, message, *, today=None, weekday_ru=None, history=None):
        """message -> validated dict (see _RESULT_SCHEMA).

        ``today`` defaults to the current date; ``weekday_ru`` to its Russian
        weekday name. Both are injected into the prompt so the model can resolve
        relative dates it would otherwise have no anchor for.

        ``history`` carries prior conversation turns (oldest→newest) so the model
        can interpret follow-ups like "подешевле" against what the user asked
        before. Each item is either a plain string (treated as a prior user
        message) or a ``{"role": "user"|"assistant", "content": ...}`` dict. Only
        the last ``_MAX_HISTORY_TURNS`` are kept to bound the token budget.
        """
        today = today or datetime.date.today()
        weekday_ru = weekday_ru or _WEEKDAYS_RU[today.weekday()]

        history_messages = _history_to_messages(history)
        messages = [{"role": "system", "content": self.system_message}]
        messages.extend(history_messages)
        messages.append(
            {
                "role": "user",
                "content": _build_user_prompt(
                    message, today, weekday_ru, has_history=bool(history_messages)
                ),
            }
        )
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=messages,
            )
            raw = completion.choices[0].message.content
        except OpenAIError as e:
            log.warning(f"QueryAnalyzer LLM call failed: {e}")
            # Degrade gracefully: treat the raw message as the semantic query.
            return self._normalize(
                {"is_event_search": True, "semantic_query": message}, message, today
            )

        return self._normalize(self._parse(raw), message, today)

    def generate_reply(self, *, message, analysis, events, relaxed_notes=None):
        """Warm 1–2 sentence intro to event-search results (a second LLM call).

        Grounded in what was actually found (count, sample titles, date range,
        price). Returns a plain string, or ``None`` on any LLM failure — the
        caller (a Celery task with ``autoretry_for=(OpenAIError,)``) must not let
        a reply-generation error retry the whole search, so we swallow it here.

        ``relaxed_notes`` (list of RU phrases) — filters that were loosened to
        find anything (e.g. "без ограничения по цене"); mentioned gently so the
        user knows the results drifted from their exact ask.

        Chit-chat turns (``is_event_search=false``) do NOT go through here — their
        reply is produced inline by :meth:`analyze` to save a request.
        """
        summary = _summarize_events_for_reply(events, analysis)
        relax_note = ""
        if relaxed_notes:
            relax_note = (
                "\nПод точный запрос ничего не было, поэтому искали шире: "
                + ", ".join(relaxed_notes)
                + ". Мягко предупреди об этом."
            )
        prompt = (
            f'Пользователь искал: "{message}".\n'
            f"Результат поиска по афише: {summary}{relax_note}\n\n"
            "Напиши короткую (1-2 предложения) живую дружелюбную подводку к этой "
            "выдаче на русском. Опирайся на то, что реально нашлось (количество, "
            "тему, даты, цену). Можно 1 эмодзи. Без Markdown, без списка событий "
            "(его покажут отдельно). Если ничего не нашлось — мягко предложи "
            "переформулировать запрос."
        )
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                temperature=0.7,
                messages=[
                    {"role": "system", "content": _REPLY_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            reply = (completion.choices[0].message.content or "").strip()
            return reply or None
        except OpenAIError as e:
            log.warning(f"QueryAnalyzer.generate_reply failed: {e}")
            return None

    @staticmethod
    def _parse(raw):
        if not raw:
            return {}
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            log.warning("QueryAnalyzer: failed to parse JSON, using empty result")
            return {}

    def _normalize(self, data, original_message, today):
        """Validate model output: clamp categories to known ids, parse ISO dates,
        coerce numeric/bool fields. Returns a dict safe to feed to the DB query.

        ``today`` anchors relative date resolution: when the model returns a
        symbolic ``relative_range`` token, we compute the concrete date window in
        Python (it overrides any explicit dates), instead of trusting the model's
        error-prone week arithmetic.
        """
        is_event_search = bool(data.get("is_event_search", True))

        semantic_query = (data.get("semantic_query") or "").strip() or original_message

        # Category names → ids, dropping anything we don't recognize.
        category_ids = []
        for name in data.get("categories") or []:
            cid = _NAME_TO_CATEGORY_ID.get(str(name).strip().lower())
            if cid is not None and cid not in category_ids:
                category_ids.append(cid)

        range_key = str(data.get("relative_range") or "").strip().lower()
        date_from, date_to = _resolve_relative_range(range_key, today)
        if date_from is None and date_to is None:
            date_from = _parse_iso_date(data.get("date_from"))
            date_to = _parse_iso_date(data.get("date_to"))

        price_max = data.get("price_max")
        try:
            price_max = int(price_max) if price_max is not None else None
            if price_max is not None and price_max < 0:
                price_max = None
        except (TypeError, ValueError):
            price_max = None

        keywords = [
            str(k).strip() for k in (data.get("keywords") or []) if str(k).strip()
        ]

        # Chit-chat reply is only meaningful for non-search turns; for event
        # searches the warm intro is generated later from the actual results.
        reply = (data.get("reply") or "").strip() if not is_event_search else ""

        return {
            "is_event_search": is_event_search,
            "semantic_query": semantic_query,
            "category_ids": category_ids,
            "date_from": date_from,
            "date_to": date_to,
            "price_max": price_max,
            "free_only": bool(data.get("free_only", False)),
            "keywords": keywords,
            "reply": reply or None,
        }


_WEEKDAYS_RU = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]


def _history_to_messages(history):
    """Normalize prior conversation turns into OpenAI chat messages.

    Accepts a list (oldest→newest) of plain strings (treated as prior user
    messages) or ``{"role", "content"}`` dicts. Unknown/missing roles fall back
    to "user"; blank content is dropped. Only the last ``_MAX_HISTORY_TURNS``
    are kept so a long thread can't blow up the token budget.
    """
    if not history:
        return []
    messages = []
    for item in history[-_MAX_HISTORY_TURNS:]:
        if isinstance(item, str):
            role, content = "user", item
        elif isinstance(item, dict):
            role = item.get("role") or "user"
            content = item.get("content") or ""
            if role not in ("user", "assistant"):
                role = "user"
        else:
            continue
        content = str(content).strip()
        if content:
            messages.append({"role": role, "content": content})
    return messages


def _summarize_events_for_reply(events, analysis):
    """Compact, LLM-friendly summary of search results for reply generation.

    Kept short (count, up to 5 titles, human date range, price hint) so the
    reply call stays cheap. ``events`` are the dicts returned by
    ``crud.search_events_by_embedding`` (dates are ISO strings).
    """
    if not events:
        return "ничего не найдено (0 событий)."

    titles = [str(e.get("title") or "").strip() for e in events if e.get("title")]
    titles = titles[:5]
    date_human = format_date_range_ru(analysis.get("date_from"), analysis.get("date_to"))

    prices = [e.get("price_int") for e in events if isinstance(e.get("price_int"), int)]
    if prices and all(p == 0 for p in prices):
        price_hint = "все бесплатные"
    elif prices and min(prices) == 0:
        price_hint = "есть бесплатные"
    else:
        price_hint = None

    parts = [f"найдено {len(events)} событий"]
    if date_human:
        parts.append(f"даты: {date_human}")
    if price_hint:
        parts.append(price_hint)
    summary = "; ".join(parts) + "."
    if titles:
        summary += " Примеры: " + "; ".join(titles) + "."
    return summary


def _resolve_relative_range(range_key, today):
    """Symbolic relative-date token → (date_from, date_to), anchored on ``today``.

    Returns ``(None, None)`` for ``"none"``/unknown tokens so the caller can fall
    back to explicit model-supplied dates. Weekday: Mon=0 … Sun=6.
    """
    if range_key not in _RELATIVE_RANGES:
        return None, None

    day = datetime.timedelta(days=1)
    weekday = today.weekday()

    if range_key == "today":
        return today, today
    if range_key == "tomorrow":
        return today + day, today + day

    # Saturday of the *current* weekend: upcoming Sat on weekdays; the ongoing
    # weekend's Sat when today is already Sat/Sun.
    if weekday >= 5:  # Sat or Sun
        this_saturday = today - datetime.timedelta(days=weekday - 5)
    else:
        this_saturday = today + datetime.timedelta(days=5 - weekday)

    if range_key == "this_weekend":
        return this_saturday, this_saturday + day
    if range_key == "next_weekend":
        next_saturday = this_saturday + datetime.timedelta(days=7)
        return next_saturday, next_saturday + day
    if range_key == "this_week":
        sunday = today + datetime.timedelta(days=(6 - weekday) % 7)
        return today, sunday
    if range_key == "next_week":
        next_monday = today + datetime.timedelta(days=7 - weekday)
        return next_monday, next_monday + datetime.timedelta(days=6)

    return None, None


_MONTHS_RU_GEN = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def format_date_range_ru(date_from, date_to):
    """Human-readable Russian date range, e.g. "25–26 июля" / "31 июля".

    Returns None when no dates are set. Collapses a same-day range to one date
    and shares the month when both dates fall in it ("25–26 июля").
    """
    if not date_from and not date_to:
        return None
    if date_from and date_to:
        if date_from == date_to:
            return f"{date_from.day} {_MONTHS_RU_GEN[date_from.month - 1]}"
        if date_from.month == date_to.month:
            return f"{date_from.day}–{date_to.day} {_MONTHS_RU_GEN[date_to.month - 1]}"
        return (
            f"{date_from.day} {_MONTHS_RU_GEN[date_from.month - 1]} – "
            f"{date_to.day} {_MONTHS_RU_GEN[date_to.month - 1]}"
        )
    single = date_from or date_to
    prefix = "с" if date_from else "до"
    return f"{prefix} {single.day} {_MONTHS_RU_GEN[single.month - 1]}"


def _parse_iso_date(value):
    """'YYYY-MM-DD' → date, anything malformed/empty → None."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value).strip()[:10])
    except (ValueError, TypeError):
        return None
