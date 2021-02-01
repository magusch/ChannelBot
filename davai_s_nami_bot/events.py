import re
import time
from collections import namedtuple
from functools import partial
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, NamedTuple

import escraper
from escraper.parsers import ALL_EVENT_TAGS, Radario, Timepad
from notion.block.collection.basic import CollectionRowBlock

from . import utils
from .logger import catch_exceptions

BAD_KEYWORDS = (
    "вебинар",
    "видеотренинг",
    "тренинг",
    "HR",
    "консультация",
)
APPROVED_ORGANIZATIONS = [
    "57992",  # Манеж
    "79462",  # Новая Голландия
    "42587",  # Молодёжный центр Эрмитажа
    "186669",  # musicAeterna
    "109981",  # ГЦСИ в Санкт-Петербурге
    "67092",  # Музей советских игровых автоматов
    "43027",  # Театр-студия
    "78132",  # Театр-фестиваль «Балтийский дом»
    "75134",  # Ленфильм
]

BORING_ORGANIZATIONS = [
    "185394",  # Арт-экспо выставки https://art-ekspo-vystavki.timepad.ru/
    "106118",  # АНО «ЦДПО — «АЛЬФА-ДИАЛОГ»
    "212547",  # Иерусалимская Сказка
    "146675",  # Корни и Крылья https://korni-i-krylya.timepad.ru
    "252995",  # Музей Христианской Культуры
    "63354",  # Семейный досуговый клуб ШтангенЦиркулб
    "181043",  # Фонд
]

CATEGORY_IDS_EXCLUDE = [
    "217",  # Бизнесс
    "376",  # Спорт
    "379",  # Для детей
    "399",  # Красота и здоровье
    "453",  # Психология и самопознание
    "1315",  # Образование за рубежом
    "452",  # ИТ и интернет
    "382",  # Иностранные языки
    "2335",  # Интеллектуальные игры
    "524",  # Хобби и творчество
    "461",  # Экскурсии и путешествия
    "462",  # Другие события
]
STARTS_AT_MIN = "{year_month_day}T11:00:00"
STARTS_AT_MAX = "{year_month_day}T23:59:00"
TIMEPAD_APPROVED_PARAMS = dict(
    limit=100,
    cities="Санкт-Петербург",
    moderation_statuses="featured, shown",
    organization_ids=", ".join(APPROVED_ORGANIZATIONS),
)
TIMEPAD_OTHERS_PARAMS = dict(
    limit=100,
    cities="Санкт-Петербург",
    moderation_statuses="featured, shown",
    organization_ids_exclude=(
        ", ".join(APPROVED_ORGANIZATIONS) + ", " + ", ".join(BORING_ORGANIZATIONS)
    ),
    price_max=500,
    category_ids_exclude=", ".join(CATEGORY_IDS_EXCLUDE),
    keywords_exclude=", ".join(BAD_KEYWORDS),
)
MAX_NEXT_DAYS = 30
two_days = timedelta(days=2)

## PARSERS
timepad_parser = Timepad()
radario_parser = Radario()


## ESCRAPER EVENTS PARSERS
def _title(event: NamedTuple):
    return event.title.replace("`", r"\`").replace("_", r"\_").replace("*", r"\*")


def _post(event: NamedTuple):
    title = _title(event)

    title = re.sub(r"[\"«](?=[^\ \.!\n])", "**«", title)
    title = re.sub(r"[\"»](?=[^a-zA-Zа-яА-Я0-9]|$)", "»**", title)

    date_from_to = date_to_post(event.date_from, event.date_to)

    title_date = "{day} {month}".format(
        day=event.date_from.day,
        month=month_name(event.date_from),
    )

    title = f"**{title_date}** {title}\n\n"

    post_text = (
        event.post_text.strip()
        .replace("`", r"\`")
        .replace("_", r"\_")
        .replace("*", r"\*")
    )

    footer = (
        "\n\n"
        f"**Где:** {event.place_name}, {event.adress} \n"
        f"**Когда:** {date_from_to} \n"
        f"**Вход:** [{event.price}] ({event.url})"
    )

    return title + post_text + footer


def weekday_name(dt: datetime):
    return utils.WEEKNAMES[dt.weekday()]


def month_name(dt: datetime):
    return utils.MONTHNAMES[dt.month]


def date_to_post(date_from: datetime, date_to: datetime):
    s_weekday = weekday_name(date_from)
    s_day = date_from.day
    s_month = month_name(date_from)
    s_hour = date_from.hour
    s_minute = date_from.minute

    if date_to is not None:
        e_day = date_to.day
        e_month = month_name(date_to)
        e_hour = date_to.hour
        e_minute = date_to.minute

        if s_day == e_day:
            start_format = f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}-"
            end_format = f"{e_hour:02}:{e_minute:02}"

        else:
            start_format = f"с {s_day} {s_month} {s_hour:02}:{s_minute:02} "
            end_format = f"по {e_day} {e_month} {e_hour:02}:{e_minute:02}"

    else:
        end_format = ""
        start_format = f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}"

    return start_format + end_format


def _url(event: NamedTuple):
    return event.url


def _from_date(event: NamedTuple):
    return event.date_from


def _to_date(event: NamedTuple):
    if event.date_to is None:
        return event.date_from + timedelta(hours=2)

    return event.date_to


def _image(event: NamedTuple):
    if event.poster_imag:
        if event.id.startswith("TIMEPAD"):
            return "https://" + event.poster_imag

    return event.poster_imag


def _event_id(event: NamedTuple):
    return event.id


def _price(event: NamedTuple):
    return event.price


##


class Event:
    _escraper_event_parsers = dict(
        title=_title,
        post=_post,
        url=_url,
        from_date=_from_date,
        to_date=_to_date,
        image=_image,
        event_id=_event_id,
        price=_price,
    )
    _tags = list(_escraper_event_parsers)

    def __new__(cls, **kwargs):
        return namedtuple("event", cls._tags)(**kwargs)

    @classmethod
    def from_escraper(cls, event: NamedTuple):
        return cls(
            **{
                tag: parse_func(event)
                for tag, parse_func in cls._escraper_event_parsers.items()
            }
        )

    @classmethod
    def from_notion_row(cls, notion_row: CollectionRowBlock, get_property_func: Callable = None):
        if get_property_func is None:
            get_property_func = notion_row.get_property

        else:
            get_property_func = partial(get_property_func, notion_row)

        return cls(**{tag: get_property_func(tag) for tag in cls._tags})


def not_approved_organization_filter(events: List[Event]):
    """
    Remove events:
    - with bad-keywords
    - with too long duration (more than two days),
    """
    good_events = list()

    for event in events:
        if (
            event is None
            or "финанс" in event.title.lower()
            or (event.to_date is not None and event.to_date - event.from_date > two_days)
            or event.image is None
        ):
            continue

        good_events.append(event)

    return good_events


@catch_exceptions()
def _get_events(
    parser: escraper.parsers.base.BaseParser, *args, **kwargs
) -> List[Event]:
    events = parser.get_events(*args, **kwargs)

    return [Event.from_escraper(event) for event in events if event.is_registration_open]


def from_approved_organizations(days: int) -> List[Event]:
    """
    Getting events from approved organizations (see. APPROVED_ORGANIZATIONS).
    Currently, only from Timepad.
    """
    return timepad_approved_organizations(days)


def timepad_approved_organizations(days: int) -> List[Event]:
    return get_timepad_events(
        days,
        TIMEPAD_APPROVED_PARAMS.copy(),
    )


def from_not_approved_organizations(days: int) -> List[Event]:
    return timepad_others_organizations(days) + radario_others_organizations(days)


def timepad_others_organizations(days: int) -> List[Event]:
    return get_timepad_events(
        days,
        TIMEPAD_OTHERS_PARAMS.copy(),
        events_filter=not_approved_organization_filter,
    )


def radario_others_organizations(days: int) -> List[Event]:
    return get_radario_events(days)


def get_timepad_events(
    days: int,
    request_params: Dict[str, Any],
    events_filter: Callable[[List[Event]], List[Event]] = None,
    with_online: bool = True,
) -> List[Event]:
    """
    Getting events.
    """
    if days > MAX_NEXT_DAYS:
        raise ValueError(
            f"Too much days for getting events: {days}."
            f"Maximum is {MAX_NEXT_DAYS} days."
        )

    today = date.today()
    request_params["starts_at_min"] = STARTS_AT_MIN.format(
        year_month_day=today.strftime("%Y-%m-%d")
    )
    request_params["starts_at_max"] = STARTS_AT_MAX.format(
        year_month_day=(today + timedelta(days=days)).strftime("%Y-%m-%d")
    )

    if with_online:
        request_params["cities"] += ", Без города"

    # for getting all events (max limit 100)
    new_events = list()
    count = 0
    new_count = 1
    while new_count > 0:
        request_params["skip"] = count

        new = _get_events(
            timepad_parser,
            request_params=request_params,
            tags=ALL_EVENT_TAGS,
        )
        new_count = len(new)

        new_events += new
        count += new_count

        time.sleep(1)

    if events_filter:
        new_events = events_filter(new_events)

    return unique(new_events)  # checking for unique -- just in case


def get_radario_events(
    days: int, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:
    category = [
        "concert",
        "theatre",
        "sport",
        "entertainment",
        "kids",
        "show",
    ]
    today = date.today()
    date_from = today.strftime(Radario.DATETIME_STRF)
    date_to = (today + timedelta(days=days)).strftime(Radario.DATETIME_STRF)

    request_params = {
        "from": date_from,
        "to": date_to,
        "category": category,
    }

    new_events = _get_events(radario_parser, request_params=request_params)

    if events_filter:
        new_events = events_filter(new_events)

    return unique(new_events)


def unique(events: List[Event]) -> List[Event]:
    return list(set(events))
