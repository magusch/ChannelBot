"""Pure functions for turning an arbitrary web page into event candidates."""

import datetime
import hashlib
import ipaddress
import json
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

MSK = ZoneInfo("Europe/Moscow")

# (parser key, pattern over a URL or raw HTML, canonical URL builder)
_KNOWN_EVENT_URLS = [
    (
        "timepad",
        re.compile(r"https?://(?:[\w-]+\.)?timepad\.ru/event/(\d+)"),
        lambda m: f"https://timepad.ru/event/{m.group(1)}/",
    ),
    (
        "ticketscloud",
        re.compile(r"https?://[\w-]+\.ticketscloud\.org/e/[0-9a-f]{24}"),
        lambda m: m.group(0),
    ),
    (
        "radario",
        re.compile(r"https?://(?:www\.)?radario\.ru/events/(\d+)"),
        lambda m: f"https://radario.ru/events/{m.group(1)}",
    ),
    (
        "qtickets",
        re.compile(r"https?://[\w-]+\.qtickets\.events/\d+[\w-]*"),
        lambda m: m.group(0),
    ),
    (
        "kassir",
        re.compile(r"https?://[\w-]+\.kassir\.ru/[\w-]+/[\w-]+"),
        lambda m: m.group(0),
    ),
    (
        "mts",
        re.compile(
            r"https?://live\.mts\.ru/[\w-]+/announcements/[\w-]+(?:\?eventId=\d+)?"
        ),
        lambda m: m.group(0),
    ),
    (
        "culture",
        re.compile(r"https?://(?:www\.)?culture\.ru/events/\d+[\w/-]*"),
        lambda m: m.group(0),
    ),
    (
        "afisha",
        re.compile(r"https?://(?:www\.)?afisha\.ru/[a-z]+/[\w-]+-\d+/"),
        lambda m: m.group(0),
    ),
    (
        "yandex",
        re.compile(r"https?://afisha\.yandex\.ru/[\w-]+/[\w-]+/[\w-]+"),
        lambda m: m.group(0),
    ),
    (
        "tripster",
        re.compile(r"https?://experience\.tripster\.ru/experience/(\d+)"),
        lambda m: f"https://experience.tripster.ru/experience/{m.group(1)}/",
    ),
]

_TIMEPAD_WIDGET = re.compile(r"data-twf2s-event--id=[\"'](\d+)")
_TC_WIDGET = re.compile(
    r"ticketscloud\.com/v1/widgets/[^\"'\s]*?[?&;]event=([0-9a-f]{24})"
)

_DROP_TAGS = [
    "script",
    "style",
    "noscript",
    "svg",
    "header",
    "footer",
    "nav",
    "form",
    "iframe",
    "template",
    "button",
]
_TICKET_WORDS = re.compile(r"билет|ticket|купить|регистрац|записат", re.IGNORECASE)
_PRICE_LINE = re.compile(r"\d[\d\s]*(?:₽|руб)|бесплатн|free", re.IGNORECASE)
_SOCIAL_HOSTS = (
    "vk.com",
    "t.me",
    "instagram.com",
    "youtube.com",
    "ok.ru",
    "yandex.ru/maps",
    "2gis.ru",
    "apps.apple.com",
    "play.google.com",
    "wa.me",
)


def route_known_url(url: str) -> Optional[Tuple[str, str]]:
    """URL of a source we scrape → (parser key, canonical URL), else None."""
    for key, pattern, canonical in _KNOWN_EVENT_URLS:
        m = pattern.match(url.strip())
        if m:
            return key, canonical(m)
    return None


def ticket_links(html: str, tc_partner: Optional[str] = None) -> List[Tuple[str, str]]:
    """Known-source event links and ticket widgets embedded in a page, in order."""
    found = []
    for key, pattern, canonical in _KNOWN_EVENT_URLS:
        for m in pattern.finditer(html):
            found.append((m.start(), key, canonical(m)))
    for m in _TIMEPAD_WIDGET.finditer(html):
        found.append((m.start(), "timepad", f"https://timepad.ru/event/{m.group(1)}/"))
    if tc_partner:
        for m in _TC_WIDGET.finditer(html):
            found.append(
                (
                    m.start(),
                    "ticketscloud",
                    f"https://{tc_partner}.ticketscloud.org/e/{m.group(1)}",
                )
            )
    seen, result = set(), []
    for _, key, url in sorted(found):
        if url not in seen:
            seen.add(url)
            result.append((key, url))
    return result


def is_public_ip(ip: str) -> bool:
    """False for loopback/private/link-local/reserved addresses (SSRF guard)."""
    addr = ipaddress.ip_address(ip)
    return addr.is_global and not addr.is_multicast


def url_event_id(url: str, index: int = 0) -> str:
    """Stable event_id for an event found on an arbitrary page."""
    digest = hashlib.sha1(url.strip().encode()).hexdigest()[:16]
    return f"URL-{digest}" + (f"-{index}" if index else "")


def parse_local_datetime(value) -> Optional[datetime.datetime]:
    """ISO string → aware datetime; naive values are Moscow local time."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.datetime.combine(
                datetime.date.fromisoformat(text[:10]), datetime.time()
            )
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK)


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _is_event_type(node) -> bool:
    return any(str(t).endswith("Event") for t in _as_list(node.get("@type")))


def _walk_jsonld(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "subEvent", "itemListElement", "item"):
            if key in node:
                yield from _walk_jsonld(node[key])


def _text(value) -> Optional[str]:
    if isinstance(value, dict):
        value = value.get("name") or value.get("url") or value.get("@id")
    if isinstance(value, list):
        value = next((v for v in value if v), None)
        return _text(value)
    value = str(value).strip() if value else ""
    return value or None


def _jsonld_address(location) -> Tuple[Optional[str], Optional[str]]:
    for loc in _as_list(location):
        if not isinstance(loc, dict):
            return None, _text(loc)
        address = loc.get("address")
        if isinstance(address, dict):
            parts = [address.get("streetAddress"), address.get("addressLocality")]
            address = ", ".join(str(p).strip() for p in parts if p)
        return _text(loc.get("name")), _text(address)
    return None, None


def _jsonld_price(offers) -> Tuple[Optional[str], Optional[int]]:
    prices = []
    for offer in _as_list(offers):
        if not isinstance(offer, dict):
            continue
        for key in ("price", "lowPrice"):
            try:
                prices.append(
                    float(str(offer.get(key)).replace(",", ".").replace(" ", ""))
                )
            except (TypeError, ValueError):
                pass
    if not prices:
        return None, None
    low = int(min(prices))
    if low == 0:
        return "Бесплатно", 0
    return (f"от {low}₽" if len(set(prices)) > 1 else f"{low}₽"), low


def jsonld_events(html: str) -> List[dict]:
    """schema.org Event objects from JSON-LD blocks, normalized to our fields."""
    soup = BeautifulSoup(html, "lxml")
    events = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "", strict=False)
        except ValueError:
            continue
        for node in _walk_jsonld(data):
            if not _is_event_type(node) or not node.get("name"):
                continue
            place, address = _jsonld_address(node.get("location"))
            price, price_int = _jsonld_price(node.get("offers"))
            events.append(
                {
                    "title": _text(node.get("name")),
                    "description": _text(node.get("description")),
                    "from_date": parse_local_datetime(node.get("startDate")),
                    "to_date": parse_local_datetime(node.get("endDate")),
                    "place": place,
                    "address": address,
                    "price": price,
                    "price_int": price_int,
                    "image": _text(node.get("image")),
                    "url": _text(node.get("url")),
                }
            )
    return [e for e in events if e["from_date"]]


def meta_image(html: str) -> Optional[str]:
    """og:image of the page."""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("meta", property="og:image") or soup.find(
        "meta", attrs={"name": "og:image"}
    )
    if not tag:
        return None
    return (tag.get("content") or "").strip() or None


def page_digest(html: str, base_url: str, max_chars: int = 6000) -> str:
    """Compact page text for the model: meta, main text, ticket links, price lines."""
    soup = BeautifulSoup(html, "lxml")
    head = []
    if soup.title and soup.title.string:
        head.append(f"Заголовок страницы: {soup.title.string.strip()}")
    for attr, name in (
        ("property", "og:title"),
        ("property", "og:description"),
        ("name", "description"),
    ):
        tag = soup.find("meta", attrs={attr: name})
        if tag and tag.get("content"):
            head.append(f"{name}: {tag['content'].strip()}")

    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        label = a.get_text(" ", strip=True)
        if href.startswith("http") and _TICKET_WORDS.search(f"{label} {href}"):
            if not any(h in href for h in _SOCIAL_HOSTS) and href not in links:
                links.append(href)

    for tag in soup(_DROP_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    lines = [ln.strip() for ln in root.get_text("\n").splitlines()]
    lines = [ln for ln in lines if ln]
    body = "\n".join(lines)

    tail = []
    if links:
        tail.append("Ссылки на билеты/регистрацию:\n" + "\n".join(links[:10]))
    head_text = "\n".join(head)
    budget = max_chars - len(head_text) - sum(len(t) for t in tail) - 20
    if len(body) > budget:
        prices = [ln for ln in lines if _PRICE_LINE.search(ln) and len(ln) < 200][:10]
        if prices:
            tail.append("Строки с ценами:\n" + "\n".join(prices))
            budget -= len(tail[-1])
        body = body[: max(budget, 0)]
    return "\n\n".join(p for p in [head_text, body, *tail] if p)


def normalize_candidate(
    raw: dict, now: datetime.datetime, category_names: List[str]
) -> Tuple[Optional[dict], Optional[str]]:
    """Validate an extracted event: (clean dict, None) or (None, reject reason)."""
    title = (raw.get("title") or "").strip()
    if not title:
        return None, "no_title"
    if raw.get("is_online"):
        return None, "online"
    if raw.get("in_city") is False:
        return None, "other_city"
    from_date = raw.get("from_date")
    if not isinstance(from_date, datetime.datetime):
        from_date = parse_local_datetime(from_date)
    to_date = raw.get("to_date")
    if not isinstance(to_date, datetime.datetime):
        to_date = parse_local_datetime(to_date)
    if from_date is None:
        return None, "no_date"
    if to_date is not None and to_date < from_date:
        to_date = None
    if (to_date or from_date) < now:
        return None, "past"
    if from_date > now + datetime.timedelta(days=550):
        return None, "too_far"

    price_int = raw.get("price_int")
    try:
        price_int = int(price_int) if price_int is not None else None
    except (TypeError, ValueError):
        price_int = None
    category = raw.get("category")
    if category not in category_names:
        category = None
    place = (raw.get("place") or "").strip()
    address = (raw.get("address") or "").strip()
    if place and address.lower().startswith(place.lower()):
        place = ""
    return {
        "title": title[:250],
        "description": (raw.get("description") or "").strip(),
        "from_date": from_date,
        "to_date": to_date or from_date + datetime.timedelta(hours=2),
        "address": ", ".join(p for p in (place, address) if p),
        "price": (raw.get("price") or "").strip() or None,
        "price_int": price_int,
        "category": category,
        "image": raw.get("image"),
        "ticket_url": raw.get("ticket_url"),
    }, None


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()
