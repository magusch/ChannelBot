"""Event from any URL: our parsers → ticket widgets → JSON-LD → cheap LLM."""

import datetime
import os
import socket
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import UnicodeDammit
from openai import OpenAI, OpenAIError

from ... import events_new
from ... import scoring
from ...logger import get_logger
from ...settings.settings_loader import settings
from .. import page_event
from .answer_parser import parse_event_answer
from .openai_models import chat_kwargs, create_chat_completion
from .query_analyzer import PROVIDER_CONFIGS, PROVIDER_OPENAI

log = get_logger(__name__)

MAX_PAGE_BYTES = 3_000_000
MAX_REDIRECTS = 5
MAX_WIDGET_LINKS = 3
MAX_EVENTS = 5
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
URL_SOURCE = "URL"


class FetchError(Exception):
    pass


@dataclass
class ExtractionResult:
    url: str
    method: Optional[str] = None
    events: List[dict] = field(default_factory=list)
    rejected: List[dict] = field(default_factory=list)
    error: Optional[str] = None
    tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "method": self.method,
            "events": [_json_safe(e) for e in self.events],
            "rejected": self.rejected,
            "error": self.error,
            "tokens": self.tokens,
        }


def _json_safe(event: dict) -> dict:
    return {
        k: (v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v)
        for k, v in event.items()
    }


def _config() -> dict:
    return (getattr(settings, "features", None) or {}).get("url_extractor") or {}


def _check_host(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("bad_url")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or None)
    except socket.gaierror:
        raise FetchError("dns")
    if not all(page_event.is_public_ip(info[4][0]) for info in infos):
        raise FetchError("private_address")


def fetch_page(url: str, timeout: float = 15) -> tuple:
    """GET a public page with SSRF and size guards → (final_url, html)."""
    for _ in range(MAX_REDIRECTS + 1):
        _check_host(url)
        try:
            resp = requests.get(
                url,
                timeout=(5, timeout),
                allow_redirects=False,
                stream=True,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
            )
        except requests.RequestException as e:
            raise FetchError(f"request: {type(e).__name__}")
        if resp.is_redirect:
            url = urljoin(url, resp.headers.get("Location", ""))
            resp.close()
            continue
        if resp.status_code >= 400:
            raise FetchError(f"http_{resp.status_code}")
        if "html" not in resp.headers.get("Content-Type", "html"):
            raise FetchError("not_html")
        body = b""
        for chunk in resp.iter_content(64 * 1024):
            body += chunk
            if len(body) > MAX_PAGE_BYTES:
                break
        resp.close()
        content_type = resp.headers.get("Content-Type", "")
        declared = (
            [content_type.split("charset=")[-1].strip()]
            if "charset=" in content_type
            else []
        )
        return url, UnicodeDammit(body, declared).unicode_markup or ""
    raise FetchError("too_many_redirects")


def _parser_call(key: str, url: str):
    """Our escraper parser for ``key`` → ParserEvent or None."""
    if key == "tripster":
        parser = events_new.get_tripster_parser()
        kwargs = {"exp_url": url}
    else:
        parser = {
            "timepad": events_new.timepad_parser,
            "ticketscloud": events_new.ticketscloud_parser,
            "radario": events_new.radario_parser,
            "qtickets": events_new.qt_parser,
            "kassir": events_new.kassir_parser,
            "mts": events_new.mts_parser,
            "culture": events_new.culture_parser,
            "afisha": events_new.afisha_parser,
            "yandex": events_new.yandex_parser,
        }.get(key)
        kwargs = {"event_url": url}
    if parser is None:
        return None
    try:
        raw = parser.get_event(tags=events_new.ALL_EVENT_TAGS, **kwargs)
    except Exception as e:
        log.warning(f"url_extractor: {key} parser failed on {url}: {e}")
        return None
    if raw is None:
        return None
    event = events_new.ParserEvent.from_parser(raw).to_dict()
    return event if event.get("title") and event.get("from_date") else None


class UrlEventExtractor:
    """Find the event(s) behind an arbitrary URL as cheaply as possible."""

    def __init__(self, fetch=fetch_page, llm=None, now=None):
        self.fetch = fetch
        self._llm = llm
        self.now = now or datetime.datetime.now(page_event.MSK)
        self.cfg = _config()

    def extract(self, url: str) -> ExtractionResult:
        url = url.strip()
        result = ExtractionResult(url=url)

        known = page_event.route_known_url(url)
        if known:
            event = _parser_call(*known)
            if event:
                result.method, result.events = "parser", [event]
                return result

        try:
            final_url, html = self.fetch(url)
        except FetchError as e:
            result.error = f"fetch: {e}"
            return result

        tc_partner = getattr(events_new.vibe_parser, "partner", None)
        links = page_event.ticket_links(html, tc_partner=tc_partner)
        if 0 < len(links) <= MAX_WIDGET_LINKS:
            found = [e for e in (_parser_call(k, u) for k, u in links) if e]
            if found:
                result.method, result.events = "widget", found
                return result

        image = page_event.meta_image(html)
        ld = page_event.jsonld_events(html)[:MAX_EVENTS]
        if ld:
            self._accept(result, ld, final_url, image, "jsonld")
            if result.events:
                return result

        self._extract_with_llm(result, html, final_url, image)
        return result

    def _accept(self, result, candidates, page_url, image, method):
        names = list(scoring.CATEGORY_ID_TO_NAME.values())
        for i, raw in enumerate(candidates):
            clean, reason = page_event.normalize_candidate(raw, self.now, names)
            if reason:
                result.rejected.append({"title": raw.get("title"), "reason": reason})
                continue
            img = clean["image"] or (image if len(candidates) == 1 else None)
            result.events.append(
                {
                    "event_id": page_event.url_event_id(page_url, i),
                    "title": clean["title"],
                    "full_text": clean["description"],
                    "url": page_url,
                    "ticket_url": clean["ticket_url"] or page_url,
                    "from_date": clean["from_date"],
                    "to_date": clean["to_date"],
                    "address": clean["address"],
                    "price": clean["price"] or "",
                    "price_int": (
                        -1 if clean["price_int"] is None else clean["price_int"]
                    ),
                    "category": clean["category"] or "",
                    "image": urljoin(page_url, img) if img else "",
                    "source": URL_SOURCE,
                }
            )
        if result.events:
            result.method = method

    # ---- LLM -----------------------------------------------------------

    def _client(self):
        if self._llm is None:
            provider = (self.cfg.get("provider") or PROVIDER_OPENAI).lower()
            pcfg = PROVIDER_CONFIGS[provider]
            kwargs = {"api_key": os.environ.get(pcfg["api_key_env"])}
            if pcfg["base_url"]:
                kwargs["base_url"] = pcfg["base_url"]
            self._llm = (OpenAI(**kwargs), self.cfg.get("model") or pcfg["model"])
        return self._llm

    def _extract_with_llm(self, result, html, page_url, image):
        digest = page_event.page_digest(
            html, page_url, max_chars=int(self.cfg.get("max_chars", 6000))
        )
        if len(digest) < 80:
            result.error = "empty_page"
            return
        client, model = self._client()
        messages = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": user_prompt(digest, page_url, self.now)},
        ]
        try:
            completion = create_chat_completion(
                client,
                model,
                messages,
                response_format={"type": "json_object"},
                **chat_kwargs(model, temperature=0.1, max_tokens=2000),
            )
        except OpenAIError as e:
            result.error = f"llm: {type(e).__name__}"
            return
        usage = getattr(completion, "usage", None)
        result.tokens = getattr(usage, "total_tokens", 0) or 0
        data = parse_event_answer(completion.choices[0].message.content)
        if not data.get("is_event_page", True) or data.get("is_promo"):
            result.rejected.append(
                {
                    "title": None,
                    "reason": "promo" if data.get("is_promo") else "not_event",
                    "note": data.get("note"),
                }
            )
            return
        candidates = [e for e in data.get("events") or [] if isinstance(e, dict)]
        self._accept(result, candidates[:MAX_EVENTS], page_url, image, "ai")


def system_prompt() -> str:
    return (
        "Ты извлекаешь мероприятия со страницы сайта для городской афиши "
        f"{settings.city_name_gen}. Пиши только то, что есть на странице: ничего не "
        "придумывай и не дополняй. Если поля нет на странице — null."
    )


def user_prompt(digest: str, page_url: str, now: datetime.datetime) -> str:
    categories = ", ".join(scoring.CATEGORY_ID_TO_NAME.values())
    weekday = [
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота",
        "воскресенье",
    ][now.weekday()]
    return f"""Сегодня {now:%Y-%m-%d}, {weekday}. Город афиши: {settings.city_name}.
Адрес страницы: {page_url}

Текст страницы:
---
{digest}
---

Ответь строго JSON:
{{
  "is_event_page": true/false,  // страница про конкретное мероприятие (или несколько) с датой
  "is_promo": true/false,       // реклама товара/услуги, курс, распродажа, розыгрыш, вакансия
  "note": "одной фразой, что это за страница",
  "events": [
    {{
      "title": "название мероприятия, как на странице, без даты",
      "description": "3-6 предложений фактов со страницы: что будет, кто участвует, формат",
      "from_date": "YYYY-MM-DDTHH:MM, местное время; если год не указан — ближайший будущий",
      "to_date": "YYYY-MM-DDTHH:MM или null",
      "place": "название площадки или null",
      "address": "улица и дом или null",
      "price": "цена текстом: 500₽ / от 800₽ / Бесплатно / null",
      "price_int": минимальная цена числом, 0 если бесплатно, null если не указана,
      "category": "одна из: {categories}",
      "ticket_url": "ссылка на покупку билета/регистрацию или null",
      "is_online": true/false,
      "in_city": true/false  // проходит в городе афиши
    }}
  ]
}}
Правила: не больше {MAX_EVENTS} мероприятий; если на странице список из многих
мероприятий (афиша площадки) — возьми ближайшие. Прошедшие не включай.
Регулярное мероприятие с несколькими датами — одно, с ближайшей датой."""
