import concurrent.futures
import re
import time
from datetime import date, datetime, timedelta
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Union,
)

from escraper.parsers import (
    ALL_EVENT_TAGS,
    MTS,
    VK,
    ConfigScraper,
    Culture,
    Kassir,
    QTickets,
    Radario,
    Telegram,
    Ticketscloud,
    Timepad,
)

from . import crud
from .helper.dsn_parameters import dsn_parameters
from .logger import catch_exceptions, get_logger
from .settings.settings_loader import settings

log = get_logger(__name__)

STARTS_AT_MIN = "{year_month_day}T10:00:00"
STARTS_AT_MAX = "{year_month_day}T23:59:00"
MAX_NEXT_DAYS = 30

DEFAULT_SCRAPER_TIMEOUT_SEC = 300


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _use_proxy(parser_name: str) -> bool:
    return settings.escraper_parameters.get(parser_name, {}).get("use_proxy", True)


def _is_scraper_enabled(scraper_name: str) -> bool:
    return settings.escraper_parameters.get(scraper_name, {}).get("enabled", True)


def get_city_param():
    cities = dsn_parameters.site_parameters("city")
    if cities:
        return cities[0]
    return settings.city


# ---------------------------------------------------------------------------
# Collector: run a scraper with timeout, keeping partial results
# ---------------------------------------------------------------------------


def _call_scraper(func: Callable, days: int, name: str) -> list:
    """Run a scraper with a wall-clock timeout, collecting events incrementally.

    `func(days)` may return a list or a generator. The worker thread drains it
    into a shared list; on timeout or mid-iteration error the events collected
    so far are returned instead of being lost. With a list-returning chain
    (current escraper) this is equivalent to the old all-or-nothing behavior.

    Timeout is read from settings.escraper_parameters.{name}.timeout_sec
    (default 300s). The abandoned thread keeps running after a timeout (a
    running future cannot be cancelled), so a snapshot copy is returned.
    """
    timeout = settings.escraper_parameters.get(name or "", {}).get(
        "timeout_sec", DEFAULT_SCRAPER_TIMEOUT_SEC
    )
    collected = []

    def drain():
        for event in func(days) or []:
            collected.append(event)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(drain)
        try:
            future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            log.warning(
                f"Scraper '{name}' exceeded {timeout}s timeout — "
                f"keeping {len(collected)} partial events"
            )
        except Exception as e:
            log.error(
                f"Scraper '{name}' raised after {len(collected)} events: {e}",
                exc_info=True,
            )
        return list(collected)
    finally:
        executor.shutdown(wait=False)


def _iter_events(parser, *args, **kwargs) -> Iterator["ParserEvent"]:
    """Lazily convert raw escraper events to ParserEvent.

    No @catch_exceptions here: on a generator it would only guard generator
    creation, never iteration. Errors propagate to the collector in
    `_call_scraper`, which logs them and keeps partial results.
    """
    for raw in parser.get_events(*args, **kwargs) or []:
        if raw is not None and raw.is_registration_open:
            yield ParserEvent.from_parser(raw)


def _apply_filter(events: Iterable, events_filter: Optional[Callable]) -> Iterable:
    """Apply a list->list filter to a materialized batch, pass through otherwise."""
    if events_filter:
        return events_filter(list(events))
    return events


@catch_exceptions()
def _get_event(parser, *args, **kwargs):
    event = parser.get_event(*args, **kwargs)
    return ParserEvent.from_parser(event)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _parse_price_int(price_str: str) -> int:
    """Extract numeric price from price string."""
    if not price_str:
        return -1
    if "бесплатн" in price_str.lower():
        return 0
    prices = re.findall(r"\d+", price_str)
    if len(prices) == 1:
        return int(prices[0])
    elif len(prices) > 1:
        prices = [int(p) for p in prices if int(p) > 100 or int(p) == 0]
        if prices:
            return min(prices)
    return -1


def _parse_datetime(value, fallback=None):
    """Parse datetime from string if needed."""
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback or datetime.today()
    return value


def not_approved_organization_filter(events: list) -> list:
    """Remove None events."""
    return [e for e in events if e is not None]


# ---------------------------------------------------------------------------
# Event data classes
# ---------------------------------------------------------------------------


class BaseEvent:
    """Base class for all event types"""

    _tags = [
        "title",
        "post",
        "full_text",
        "url",
        "ticket_url",
        "from_date",
        "to_date",
        "image",
        "event_id",
        "price",
        "price_int",
        "category",
        "address",
        "source",
    ]

    _additional_tags = [
        "id",
        "queue",
        "prepared_text",
        "status",
        "post_url",
        "place_id",
        "is_ready",
        "explored_date",
        "post_date",
        "main_category_id",
        "image_upload",
    ]

    _all_tags = _tags + _additional_tags

    # Default values per field type
    _defaults = {
        "price_int": -1,
        "from_date": None,
        "to_date": None,
    }

    def __init__(self, **kwargs):
        self._data = {}
        self._additional = {}

        for tag in self._tags:
            default = self._defaults.get(tag, "")
            self._data[tag] = kwargs.get(tag, default)

        for tag in self._additional_tags:
            self._additional[tag] = kwargs.get(tag)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        if name in self._data:
            return self._data[name]
        if name in self._additional:
            return self._additional[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def _asdict(self) -> Dict[str, Any]:
        """Return dict of main fields (namedtuple compatibility)."""
        return self._data.copy()

    def to_dict(self) -> Dict[str, Any]:
        result = self._data.copy()
        result.update({k: v for k, v in self._additional.items() if v is not None})
        return result

    @classmethod
    def _default_for(cls, tag: str):
        if "date" in tag:
            return datetime.today()
        if tag in ["id", "queue", "place_id", "main_category_id"]:
            return None
        if tag == "is_ready":
            return False
        return ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any], columns=None) -> "BaseEvent":
        if columns is None:
            columns = cls._all_tags

        event_dict = {}
        for tag in columns:
            if tag in data:
                value = data[tag]
                if (
                    tag in ["from_date", "to_date", "explored_date", "post_date"]
                    and value is not None
                ):
                    value = _parse_datetime(value)
                event_dict[tag] = value
            else:
                event_dict[tag] = cls._default_for(tag)

        return cls(**event_dict)


class ParserEvent(BaseEvent):
    """Event created from parser data"""

    _escraper_event_parsers = {
        "title": lambda e: e.title.replace("`", r"\`")
        .replace("_", r"\_")
        .replace("*", r"\*"),
        "post": lambda e: e.post_text,
        "full_text": lambda e: e.full_text,
        "url": lambda e: e.url,
        "ticket_url": lambda e: e.ticket_url,
        "from_date": lambda e: e.date_from,
        "to_date": lambda e: e.date_to or (e.date_from + timedelta(hours=2)),
        "image": lambda e: (
            f"https://{e.poster_imag}"
            if e.id.startswith("TIMEPAD") and e.poster_imag
            else e.poster_imag
        ),
        "event_id": lambda e: e.id,
        "price": lambda e: e.price,
        "price_int": lambda e: _parse_price_int(e.price),
        "category": lambda e: e.category,
        "address": lambda e: f"{e.place_name}, {e.adress}",
        "source": lambda e: e.source,
    }

    @classmethod
    def from_parser(cls, event: NamedTuple) -> "ParserEvent":
        data = {}
        for tag, parse_func in cls._escraper_event_parsers.items():
            try:
                data[tag] = parse_func(event)
            except (AttributeError, TypeError):
                data[tag] = ""
        return cls(**data)


class DatabaseEvent(BaseEvent):
    """Event created from database record"""

    _date_fields = ["from_date", "to_date", "explored_date", "post_date"]

    @classmethod
    def from_database(
        cls,
        data: Union[tuple, Dict[str, Any]],
        columns: Optional[List[str]] = None,
    ) -> "DatabaseEvent":
        if columns is None:
            columns = cls._all_tags

        event_dict = {}

        # SQLAlchemy model object
        if hasattr(data, "__table__"):
            for column in data.__table__.columns:
                value = getattr(data, column.name)
                if column.name in cls._date_fields and value is not None:
                    value = _parse_datetime(value, datetime.today())
                event_dict[column.name] = value

        elif isinstance(data, dict):
            for tag in columns:
                if tag in data:
                    value = data[tag]
                    if tag in cls._date_fields and value is not None:
                        value = _parse_datetime(value, datetime.today())
                    event_dict[tag] = value
                else:
                    event_dict[tag] = cls._default_for(tag)

        # tuple / sequence
        else:
            for i, tag in enumerate(columns):
                if i < len(data):
                    value = data[i]
                    if tag in cls._date_fields and value is not None:
                        value = _parse_datetime(value, datetime.today())
                    event_dict[tag] = value
                else:
                    event_dict[tag] = cls._default_for(tag)

        return cls(**event_dict)


class EventFactory:
    """Factory for creating events from different sources"""

    @staticmethod
    def from_parser(event: NamedTuple) -> ParserEvent:
        return ParserEvent.from_parser(event)

    @staticmethod
    def from_database(
        data: Union[tuple, Dict[str, Any]],
        columns: Optional[List[str]] = None,
    ) -> DatabaseEvent:
        return DatabaseEvent.from_database(data, columns)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> BaseEvent:
        return BaseEvent.from_dict(data)


# Compatibility alias for events.py's Event: supports both Event.from_database
# (crud.py, dsn_site.py) and Event.from_dict (celery_tasks.py).
Event = DatabaseEvent


# ---------------------------------------------------------------------------
# Parser instances
# ---------------------------------------------------------------------------

timepad_parser = Timepad(use_proxy=_use_proxy("timepad"))
timepad_parser.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
radario_parser = Radario(use_proxy=_use_proxy("radario"))
ticketscloud_parser = Ticketscloud(use_proxy=_use_proxy("ticketscloud"))
vk_parser = VK(use_proxy=_use_proxy("vk"))
qt_parser = QTickets(use_proxy=_use_proxy("qtickets"))
mts_parser = MTS(use_proxy=_use_proxy("mts"))
culture_parser = Culture(use_proxy=_use_proxy("culture"))
tg_parser = Telegram(use_proxy=_use_proxy("tg"))
cfg_parser = ConfigScraper(use_proxy=_use_proxy("cfg"))
kassir_parser = Kassir(use_proxy=_use_proxy("kassir"))


# ---------------------------------------------------------------------------
# ScrapeEvents — all scraper logic lives here
# ---------------------------------------------------------------------------


class ScrapeEvents:
    """Unified scraper for all event sources.

    Per-source `get_*_events` methods are lazy generators (no timeout, no
    enabled-check). Public entry points (`run_scraper`, `get_events`,
    `from_approved_organizations`, `from_not_approved_organizations`) wrap
    them with `_call_scraper`, which adds the timeout and keeps partial
    results, and check the `enabled` flag in settings.

    Usage::

        scraper = ScrapeEvents()
        events = scraper.run_scraper('timepad', days=7)
        events = scraper.from_approved_organizations(days=7)
    """

    _timepad_parser = timepad_parser
    _radario_parser = radario_parser
    _ticketscloud_parser = ticketscloud_parser
    _vk_parser = vk_parser
    _qt_parser = qt_parser
    _mts_parser = mts_parser
    _culture_parser = culture_parser
    _tg_parser = tg_parser
    _cfg_parser = cfg_parser
    _kassir_parser = kassir_parser

    PARSER_URLS = {
        "timepad.ru": _timepad_parser,
        "vk.": _vk_parser,
        "ticketscloud.": _ticketscloud_parser,
        "radario.ru": _radario_parser,
        "qtickets.events": _qt_parser,
        "live.mts.ru": _mts_parser,
        "culture.ru": _culture_parser,
        "t.me": _tg_parser,
        "kassir.ru": _kassir_parser,
    }

    def __init__(self, session=None):
        self.session = session
        self.escraper_sites = {
            "timepad": self.get_timepad_events,
            "radario": self.get_radario_events,
            "ticketscloud": self.get_ticketscloud_events,
            "vk": self.get_vk_events,
            "qtickets": self.get_qtickets_events,
            "mts": self.get_mts_events,
            "culture": self.get_culture_events,
            "tg": self.get_tg_posts,
            "cfg": self.get_cfg_events,
            "kassir": self.get_kassir_events,
        }

    # ------------------------------------------------------------------
    # Public entry points (timeout + enabled-check)
    # ------------------------------------------------------------------

    def run_scraper(self, name: str, days: int, **kwargs) -> List[ParserEvent]:
        """Run a single scraper by name; returns a list, never raises."""
        if name not in self.escraper_sites:
            raise ValueError(f"Unknown source: {name}")
        if not _is_scraper_enabled(name):
            log.info(f"Scraper '{name}' is disabled in settings, skipping.")
            return []
        func = self.escraper_sites[name]
        if kwargs:
            return _call_scraper(lambda d: func(d, **kwargs), days, name)
        return _call_scraper(func, days, name)

    def get_events(self, source: str, days: int, **kwargs) -> List[ParserEvent]:
        return self.run_scraper(source, days, **kwargs)

    def from_approved_organizations(self, days: int) -> List[ParserEvent]:
        """Get events from approved organizations (currently only Timepad)."""
        weekday = date.today().weekday()
        if weekday % 2 != 0:
            return []
        return self.run_scraper(
            "timepad",
            days,
            request_params=self._timepad_request_params(approved=True),
        )

    def from_not_approved_organizations(self, days: int) -> List[ParserEvent]:
        """Get events from non-approved organizations, alternating by weekday."""
        events_list = []
        weekday = date.today().weekday()

        if weekday % 2 == 1:
            for name in ("qtickets", "ticketscloud"):
                events_list += self.run_scraper(name, days * 2)
        else:
            for name in ("timepad", "radario"):
                events_list += self.run_scraper(name, days)

        if weekday == 6:
            events_list += self.run_scraper("vk", days)

        if weekday == 0 or weekday == 4:
            events_list += self.run_scraper("mts", days)
        elif weekday == 2 or weekday == 5:
            events_list += self.run_scraper("culture", days)

        return events_list

    # ------------------------------------------------------------------
    # Timepad
    # ------------------------------------------------------------------

    @staticmethod
    def _timepad_request_params(approved: bool = False) -> Dict:
        timepad_params = dsn_parameters.read_param("timepad")
        timepad_settings = settings.escraper_parameters.get("timepad", {})

        params = dict(
            limit=100,
            cities="Санкт-Петербург",
            moderation_statuses="featured, shown",
        )

        if timepad_params:
            if not approved:
                params["price_max"] = 5000
                tp_city = timepad_params.get("city")
                if tp_city:
                    params["cities"] = tp_city[0]
                elif timepad_settings:
                    params["cities"] = timepad_settings.get("city", "Санкт-Петербург")

                tp_price = timepad_params.get("price_max")
                if tp_price:
                    params["price_max"] = tp_price[0]
                elif timepad_settings:
                    params["price_max"] = timepad_settings.get("price_max", 5000)

                if timepad_params.get("approved_organization") or timepad_params.get(
                    "boring_organization"
                ):
                    params["organization_ids_exclude"] = ", ".join(
                        timepad_params.get("approved_organization", [])
                        + timepad_params.get("boring_organization", [])
                    )
                if timepad_params.get("exclude_categories"):
                    params["category_ids_exclude"] = ", ".join(
                        timepad_params["exclude_categories"]
                    )
                if timepad_params.get("bad_keywords"):
                    params["keywords_exclude"] = ", ".join(
                        timepad_params["bad_keywords"]
                    )
            else:
                params["organization_ids"] = timepad_params.get(
                    "approved_organization", []
                )
        elif approved:
            params["organization_ids"] = []

        if params["limit"] > 100:
            params["limit"] = 100

        return params

    def get_timepad_events(
        self,
        days: int,
        request_params: Optional[Dict] = None,
        events_filter: Optional[Callable] = None,
        with_online: bool = False,
    ) -> Iterator[ParserEvent]:
        days = int(settings.escraper_parameters.get("timepad", {}).get("days", days))
        if days > MAX_NEXT_DAYS:
            raise ValueError(
                f"Too many days for getting events: {days}. " f"Max is {MAX_NEXT_DAYS}."
            )

        today = date.today() + timedelta(days=1)

        # NOTE: existed_event_ids is not passed to escraper — it's too big
        if request_params is None:
            request_params = self._timepad_request_params()

        request_params["starts_at_min"] = STARTS_AT_MIN.format(
            year_month_day=today.strftime("%Y-%m-%d")
        )
        request_params["starts_at_max"] = STARTS_AT_MAX.format(
            year_month_day=(today + timedelta(days=days)).strftime("%Y-%m-%d")
        )

        if with_online:
            request_params["cities"] += ", Без города"

        # Paginated: each page is a natural batch for the collector
        seen_ids = set()
        count = 0
        while True:
            request_params["skip"] = count
            page = list(
                _iter_events(
                    self._timepad_parser,
                    request_params=request_params,
                    tags=ALL_EVENT_TAGS,
                )
            )
            new = [e for e in page if e.event_id not in seen_ids]
            seen_ids.update(e.event_id for e in page)
            if not new:
                break
            count += len(new)
            yield from _apply_filter(new, events_filter)
            time.sleep(1)

    # ------------------------------------------------------------------
    # Radario
    # ------------------------------------------------------------------

    def get_radario_events(
        self, days: int, events_filter: Optional[Callable] = None
    ) -> Iterator[ParserEvent]:
        default_categories = [
            "concert",
            "theatre",
            "sport",
            "entertainment",
            "kids",
            "show",
        ]
        days = int(settings.escraper_parameters.get("radario", {}).get("days", days))
        today = date.today()
        date_from = (today + timedelta(days=1)).strftime(Radario.DATETIME_STRF)
        date_to = (today + timedelta(days=days)).strftime(Radario.DATETIME_STRF)

        radario_city = settings.escraper_parameters.get("radario", {}).get("city", "spb")
        radario_cities = dsn_parameters.read_param("radario").get("city")
        if radario_cities:
            radario_city = radario_cities[0]

        categories = settings.escraper_parameters.get("radario", {}).get(
            "categories", default_categories
        )

        request_params = {
            "from": date_from,
            "to": date_to,
            "category": categories,
            "city": radario_city,
        }
        existed_event_ids = crud.get_event_id_by_prefix("RADARIO")
        yield from _apply_filter(
            _iter_events(
                self._radario_parser,
                request_params=request_params,
                existed_event_ids=existed_event_ids,
            ),
            events_filter,
        )

    # ------------------------------------------------------------------
    # Ticketscloud
    # ------------------------------------------------------------------

    def get_ticketscloud_events(
        self, days: int, events_filter: Optional[Callable] = None
    ) -> Iterator[ParserEvent]:
        tc_org_ids = dsn_parameters.read_param("ticketscloud").get("org_id", [])
        tc_org_ids += settings.escraper_parameters.get("ticketscloud", {}).get(
            "org_id", []
        )

        ts_cities = dsn_parameters.read_param("ticketscloud").get("city")
        ts_city = settings.escraper_parameters.get("ticketscloud", {}).get(
            "city", "Санкт-Петербург"
        )
        if ts_cities:
            ts_city = ts_cities[0]

        request_params = {
            "city": ts_city,
            "days": settings.escraper_parameters.get("ticketscloud", {}).get("days", 10),
        }
        if tc_org_ids:
            request_params["org_ids"] = list(set(tc_org_ids))

        existed_event_ids = crud.get_event_id_by_prefix("TC")
        yield from _apply_filter(
            _iter_events(
                self._ticketscloud_parser,
                request_params=request_params,
                tags=ALL_EVENT_TAGS,
                existed_event_ids=existed_event_ids,
            ),
            events_filter,
        )

    # ------------------------------------------------------------------
    # VK
    # ------------------------------------------------------------------

    def get_vk_events(
        self, days: int = None, events_filter: Optional[Callable] = None
    ) -> Iterator[ParserEvent]:
        days = settings.escraper_parameters.get("vk", {}).get("days", days * 2)

        vk_city_id = settings.escraper_parameters.get("vk", {}).get("vk_city_id", "2")
        vk_city = settings.escraper_parameters.get("vk", {}).get(
            "vk_city", "Санкт-Петербург"
        )

        vk_param = dsn_parameters.read_param("vk")
        if vk_param:
            if vk_param.get("city_id"):
                vk_city_id = vk_param["city_id"][0]
            if vk_param.get("city"):
                vk_city = vk_param["city"][0]

        request_params = {
            "days": days,
            "city_id": vk_city_id,
            "city": vk_city,
        }
        existed_event_ids = crud.get_event_id_by_prefix("VK")
        yield from _apply_filter(
            _iter_events(
                self._vk_parser,
                request_params=request_params,
                existed_event_ids=existed_event_ids,
            ),
            events_filter,
        )

    # ------------------------------------------------------------------
    # QTickets
    # ------------------------------------------------------------------

    def get_qtickets_events(
        self, days: int = None, events_filter: Optional[Callable] = None
    ) -> Iterator[ParserEvent]:
        days = settings.escraper_parameters.get("qtickets", {}).get("days", days)

        qt_city = settings.escraper_parameters.get("qtickets", {}).get("city", "spb")
        qt_cities = dsn_parameters.read_param("qtickets").get("city")
        if qt_cities:
            qt_city = qt_cities[0]

        request_params = {"days": days, "city": qt_city}
        existed_event_ids = crud.get_event_id_by_prefix("QT")
        yield from _apply_filter(
            _iter_events(
                self._qt_parser,
                request_params=request_params,
                tags=ALL_EVENT_TAGS,
                existed_event_ids=existed_event_ids,
            ),
            events_filter,
        )

    # ------------------------------------------------------------------
    # MTS
    # ------------------------------------------------------------------

    def get_mts_events(
        self, days: int = None, events_filter: Optional[Callable] = None
    ) -> Iterator[ParserEvent]:
        days = settings.escraper_parameters.get("mts", {}).get("days", days)

        mts_city = settings.escraper_parameters.get("mts", {}).get(
            "city", "sankt-peterburg"
        )
        mts_cities = dsn_parameters.read_param("mts").get("city")
        if mts_cities:
            mts_city = mts_cities[0]

        mts_categories = dsn_parameters.read_param("mts").get("category")
        if not mts_categories:
            mts_categories = settings.escraper_parameters.get("mts", {}).get(
                "categories",
                [
                    "ribbon",
                    "concerts",
                    "theater",
                    "musicals",
                    "show",
                    "exhibitions",
                    "sport",
                ],
            )

        request_params = {
            "city": mts_city,
            "categories": mts_categories,
            "days": days,
        }
        existed_event_ids = crud.get_event_id_by_prefix("MTS")
        yield from _apply_filter(
            _iter_events(
                self._mts_parser,
                request_params=request_params,
                tags=ALL_EVENT_TAGS,
                existed_event_ids=existed_event_ids,
            ),
            events_filter,
        )

    # ------------------------------------------------------------------
    # Culture.ru
    # ------------------------------------------------------------------

    def get_culture_events(
        self, days: int = None, events_filter: Optional[Callable] = None
    ) -> Iterator[ParserEvent]:
        days = settings.escraper_parameters.get("culture", {}).get("days", days)

        culture_city = settings.escraper_parameters.get("culture", {}).get(
            "city", "sankt-peterburg"
        )
        culture_cities = dsn_parameters.read_param("culture").get("city")
        if culture_cities:
            culture_city = culture_cities[0]

        request_params = {"city": culture_city, "days": days}
        existed_event_ids = crud.get_event_id_by_prefix("CLTR")
        yield from _apply_filter(
            _iter_events(
                self._culture_parser,
                request_params=request_params,
                tags=ALL_EVENT_TAGS,
                existed_event_ids=existed_event_ids,
            ),
            events_filter,
        )

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    def get_tg_posts(
        self, days: int = None, events_filter: Optional[Callable] = None
    ) -> Iterator[ParserEvent]:
        days = int(settings.escraper_parameters.get("tg", {}).get("days", days))
        channels = settings.escraper_parameters.get("tg", {}).get("channels", [])
        existed_event_ids = crud.get_event_id_by_prefix("TG")

        request_params = {"channels": channels, "days": days}
        yield from _apply_filter(
            _iter_events(
                self._tg_parser,
                request_params=request_params,
                tags=ALL_EVENT_TAGS,
                existed_event_ids=existed_event_ids,
            ),
            events_filter,
        )

    # ------------------------------------------------------------------
    # ConfigScraper (sevcable, newholland, etc.)
    # ------------------------------------------------------------------

    def get_cfg_events(
        self, days: int = None, events_filter: Optional[Callable] = None
    ) -> Iterator[ParserEvent]:
        days = int(settings.escraper_parameters.get("cfg", {}).get("days", days))
        sites = settings.escraper_parameters.get("cfg", {}).get(
            "sites",
            ["sevcable", "newholland", "levashovsky", "alexandrinsky"],
        )
        existed_event_ids = crud.get_event_id_by_prefix("CFG")

        # Per-site batches: an error on one site doesn't lose the others
        for site in sites:
            request_params = {"site": site, "days": days}
            try:
                site_events = list(
                    _iter_events(
                        self._cfg_parser,
                        request_params=request_params,
                        tags=ALL_EVENT_TAGS,
                        existed_event_ids=existed_event_ids,
                    )
                )
            except Exception as e:
                log.error(f"Error getting events from {site}: {e}")
                site_events = []
            yield from _apply_filter(site_events, events_filter)
            time.sleep(1)

    # ------------------------------------------------------------------
    # Kassir
    # ------------------------------------------------------------------

    def get_kassir_events(
        self, days: int = None, events_filter: Optional[Callable] = None
    ) -> Iterator[ParserEvent]:
        days = settings.escraper_parameters.get("kassir", {}).get("days", days)

        kassir_city_domain = settings.escraper_parameters.get("kassir", {}).get(
            "city_domain", "spb.kassir.ru"
        )
        kassir_cities = dsn_parameters.read_param("kassir").get("city_domain")
        if kassir_cities:
            kassir_city_domain = kassir_cities[0]

        kassir_categories = dsn_parameters.read_param("kassir").get("categories")
        if not kassir_categories:
            kassir_categories = settings.escraper_parameters.get("kassir", {}).get(
                "categories", ["koncert", "teatr", "shou", "festivali", "sport"]
            )

        request_params = {
            "city_domain": kassir_city_domain,
            "categories": kassir_categories,
            "days": days,
        }
        existed_event_ids = crud.get_event_id_by_prefix("KASSIR")
        yield from _apply_filter(
            _iter_events(
                self._kassir_parser,
                request_params=request_params,
                tags=ALL_EVENT_TAGS,
                existed_event_ids=existed_event_ids,
            ),
            events_filter,
        )

    # ------------------------------------------------------------------
    # Single event by URL
    # ------------------------------------------------------------------

    def from_url(self, event_url: str) -> Optional[ParserEvent]:
        """Get event by URL, matching against known parser URL patterns."""
        for parser_base_url, parser in self.PARSER_URLS.items():
            if parser_base_url in event_url:
                return _get_event(parser, event_url=event_url)
        return None

    # ------------------------------------------------------------------
    # Database operations (require session)
    # ------------------------------------------------------------------

    def save_events(self, events: List[BaseEvent]) -> List[DatabaseEvent]:
        if not self.session:
            raise ValueError("Session is required to save events")

        saved_events = []
        for event in events:
            try:
                saved_event = crud.create_event(self.session, event.to_dict())
                saved_events.append(DatabaseEvent.from_database(saved_event))
            except Exception as e:
                log.error(f"Error saving event {event.event_id}: {e}")
        return saved_events

    def get_ready_to_post(self) -> List[DatabaseEvent]:
        if not self.session:
            raise ValueError("Session is required to get events")
        events = crud.get_ready_to_post(self.session)
        return [DatabaseEvent.from_database(e) for e in events]

    def get_event_by_id(self, event_id: str) -> Optional[DatabaseEvent]:
        if not self.session:
            raise ValueError("Session is required to get event")
        event = crud.get_event_by_id(self.session, event_id)
        return DatabaseEvent.from_database(event) if event else None


# ---------------------------------------------------------------------------
# Module-level API — delegates to a default ScrapeEvents instance.
#
# Mirrors events.py so celery_tasks.py can switch from
# `events.from_approved_organizations(days=7)` to
# `events_new.from_approved_organizations(days=7)` with an import change.
# `escraper_sites` maps to raw generator methods, so the existing
# `events._call_scraper(events.escraper_sites[site], days, site)` call in
# celery_tasks.py keeps working as-is.
# ---------------------------------------------------------------------------

_default_scraper = ScrapeEvents()

escraper_sites = _default_scraper.escraper_sites

PARSER_URLS = ScrapeEvents.PARSER_URLS


def from_approved_organizations(days: int) -> List[ParserEvent]:
    return _default_scraper.from_approved_organizations(days)


def from_not_approved_organizations(days: int) -> List[ParserEvent]:
    return _default_scraper.from_not_approved_organizations(days)


def from_url(event_url: str) -> Optional[ParserEvent]:
    return _default_scraper.from_url(event_url)


def run_scraper(name: str, days: int, **kwargs) -> List[ParserEvent]:
    return _default_scraper.run_scraper(name, days, **kwargs)


# ---------------------------------------------------------------------------
# EventParser — backward compatibility alias
# ---------------------------------------------------------------------------


class EventParser:
    """Parser for different event sources (delegates to ScrapeEvents)."""

    def __init__(self):
        self._scraper = ScrapeEvents()

    def get_events(self, source: str, days: int, **kwargs) -> List[ParserEvent]:
        return self._scraper.get_events(source, days, **kwargs)

    def get_event(self, url: str) -> Optional[ParserEvent]:
        return self._scraper.from_url(url)

    @staticmethod
    def from_url(url: str) -> Optional[ParserEvent]:
        return _default_scraper.from_url(url)
