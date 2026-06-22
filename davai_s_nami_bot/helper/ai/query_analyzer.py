# -*- coding: utf-8 -*-
"""Natural-language search-query analyzer.

Turns a free-text user message ("джазовый концерт в выходные") into a structured
search intent: a clean semantic query for the embedding model plus hard filters
(dates, categories, price) that the LLM cannot express through similarity alone.

Uses Gemini via its OpenAI-compatible endpoint — same client pattern as
``GeminiHelper`` and ``EmbeddingClient`` so the whole RAG path stays on one
provider. The model does NOT know the current date, so the caller passes today's
date and weekday and we ask it to resolve relative phrases ("в выходные",
"завтра", "на следующей неделе") into concrete ISO dates. Everything the model
returns is validated/normalized in Python before it reaches the DB query.
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
    "date_from": "<YYYY-MM-DD или null>",
    "date_to": "<YYYY-MM-DD или null>",
    "price_max": "<число или null>",
    "free_only": False,
    "keywords": ["<ключевое слово>"],
}

_SYSTEM_FALLBACK = (
    "Ты — анализатор поисковых запросов для афиши мероприятий Санкт-Петербурга. "
    "Пользователь пишет свободный текст, ты превращаешь его в структуру для "
    "семантического поиска. Возвращай только JSON, без пояснений."
)


# Keep follow-up context bounded so a long chat can't blow up the token budget.
_MAX_HISTORY_TURNS = 6


def _build_user_prompt(message, today, weekday_ru, has_history=False):
    categories = ", ".join(_CATEGORY_NAMES)
    schema = json.dumps(_RESULT_SCHEMA, ensure_ascii=False, indent=2)
    context_note = (
        "Выше — предыдущие сообщения этого же диалога. Если текущий запрос — "
        'уточнение к ним (например «подешевле», «а в субботу?», «только '
        'бесплатные»), пойми из контекста, о чём шла речь, и дополни/измени '
        "фильтры соответственно. Если это новый самостоятельный запрос — "
        "игнорируй предыдущие сообщения.\n\n"
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
  болтовня, бессмыслица). В этом случае остальные поля можно оставить пустыми.
- semantic_query: суть запроса для векторного поиска. Убери служебные слова про
  дату/цену/город, оставь тему и характер мероприятия. Можно слегка расширить
  синонимами ("джазовый концерт" → "джазовый концерт живая музыка").
- categories: ноль или несколько названий ТОЛЬКО из этого списка: {categories}.
  Если категория не очевидна — верни пустой список.
- date_from / date_to: диапазон дат (YYYY-MM-DD) или null. "в выходные" —
  ближайшие суббота и воскресенье; "завтра" — date_from=date_to=завтра.
- price_max: верхний предел цены в рублях, если упомянут ("до 1000 рублей"),
  иначе null. free_only: true только если просят бесплатное.
- keywords: важные слова из запроса (тема, жанр), которые стоит учесть.
"""


class QueryAnalyzer:
    """Parse a free-text query into a structured, validated search intent."""

    def __init__(self, dsn_param):
        api_key = os.environ.get("GEMINI_API")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.system_message = (
            dsn_param.site_parameters("query_analyzer_system_message", last=1)
            or _SYSTEM_FALLBACK
        )
        self.model = (
            dsn_param.site_parameters("query_analyzer_model", last=1)
            or "gemini-2.5-flash"
        )

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
                {"is_event_search": True, "semantic_query": message}, message
            )

        return self._normalize(self._parse(raw), message)

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

    def _normalize(self, data, original_message):
        """Validate model output: clamp categories to known ids, parse ISO dates,
        coerce numeric/bool fields. Returns a dict safe to feed to the DB query.
        """
        is_event_search = bool(data.get("is_event_search", True))

        semantic_query = (data.get("semantic_query") or "").strip() or original_message

        # Category names → ids, dropping anything we don't recognize.
        category_ids = []
        for name in data.get("categories") or []:
            cid = _NAME_TO_CATEGORY_ID.get(str(name).strip().lower())
            if cid is not None and cid not in category_ids:
                category_ids.append(cid)

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

        return {
            "is_event_search": is_event_search,
            "semantic_query": semantic_query,
            "category_ids": category_ids,
            "date_from": date_from,
            "date_to": date_to,
            "price_max": price_max,
            "free_only": bool(data.get("free_only", False)),
            "keywords": keywords,
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


def _parse_iso_date(value):
    """'YYYY-MM-DD' → date, anything malformed/empty → None."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value).strip()[:10])
    except (ValueError, TypeError):
        return None
