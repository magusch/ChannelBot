import re
import time
from collections import namedtuple
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any, Callable, Dict, List, NamedTuple

import escraper
from escraper.parsers import ALL_EVENT_TAGS, Radario, Timepad, Ticketscloud, VK

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
    "57992",   # Манеж
    "79462",   # Новая Голландия
    "42587",   # Молодёжный центр Эрмитажа
    "186669",  # musicAeterna
    "109981",  # ГЦСИ в Санкт-Петербурге
    "67092",   # Музей советских игровых автоматов
    "43027",   # Театр-студия
    "78132",   # Театр-фестиваль «Балтийский дом»
    "75134",   # Ленфильм
    "191811",  # Планетарий 1
    "130063",  # МИСП
    "267817",  # Маяковка
    "30148",   # ЦСИ Курёхина
    "112209",  # Севкабель
]

BORING_ORGANIZATIONS = [
    "185394",  # Арт-экспо выставки https://art-ekspo-vystavki.timepad.ru/
    "106118",  # АНО «ЦДПО — «АЛЬФА-ДИАЛОГ»
    "212547",  # Иерусалимская Сказка
    "146675",  # Корни и Крылья https://korni-i-krylya.timepad.ru
    "252995",  # Музей Христианской Культуры
    "63354",   # Семейный досуговый клуб ШтангенЦиркулб
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
STARTS_AT_MIN = "{year_month_day}T10:00:00"
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
    price_max=1200,
    category_ids_exclude=", ".join(CATEGORY_IDS_EXCLUDE),
    keywords_exclude=", ".join(BAD_KEYWORDS),
)
MAX_NEXT_DAYS = 30
two_days = timedelta(days=2)

TICKETSCLOUD_ORG_IDS = ['5dce558174fd6b0bcaa66524','5e3d551b44d20ecf697408e4', '5e3bec5fea9c82d6958f8551', '5d0fb0e759d59a1095ea1b2d',
                        '606afea333c340d4ee51b001','5f73840e094c46ba38df3426','5cb9f1fbad3df9000c9d6c6a','5f5234d89aa0cd1e7d380866',
                        '5fd84f24ae1e29b732c6756c','5dd47966c189df3040c1ae3a', '5bb25b9ee5b64d000cfcc38c', '5c01321a269b85000becd652',
                        '5c7950a93df5de000c93e287', '5f75c8e17540a6f988fa0a1f', '6036cfb79ad7272eea7734bf', '5f104439d473aea92c126338',
                        '5daf03692c4c8cd18ef6b0da','5bb3766290566f000b409adf','5d8cd897cb535bfd631b7348', '5f5a3a5e50f7d892d28ffdb5',
                        '5f6d96bf06a12bb6586080c4', '5c6eac03afa1a9000cc77e34', '5e060d4c36db15fb7f777ae8', '60a44a97d54ac08a34b10301' ]


## PARSERS
timepad_parser = Timepad()
radario_parser = Radario()
ticketscloud_parser = Ticketscloud()
vk_parser = VK()

PARSER_URLS = {
    'timepad.ru': timepad_parser, 'vk.': vk_parser  #'ticketscloud.org' : ticketscloud_parser, 'radario.ru': radario_parser,
}

## ESCRAPER EVENTS PARSERS
def _title(event: NamedTuple):
    return event.title.replace("`", r"\`").replace("_", r"\_").replace("*", r"\*")


def _post(event: NamedTuple):
    title = _title(event)

    title = re.sub(r"[\"«](?=[^\ \.!\n])", "*«", title)
    title = re.sub(r"[\"»](?=[^a-zA-Zа-яА-Я0-9]|$)", "»*", title)

    date_from_to = date_to_post(event.date_from, event.date_to)

    title_date = "{day} {month}".format(
        day=event.date_from.day,
        month=month_name(event.date_from),
    )

    title = f"*{title_date}* {title}\n\n"

    post_text = (
        event.post_text.strip()
        .replace("`", r"\`")
        .replace("_", r"\_")
        .replace("*", r"\*")
    )

    footer = (
        "\n\n"
        f"*Где:* {event.place_name}, {event.adress} \n"
        f"*Когда:* {date_from_to} \n"
        f"*Вход:* [{event.price}]({event.url})"
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


def _address(event: NamedTuple):
    return f"{event.place_name}, {event.adress}"


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
        address=_address,
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
    def from_database(cls, data: tuple, columns=_tags):
        """
        Создание объекта `Event` из записи базы данных.

        Parameters
        ----------
        data : tuple
            Строчка данных из базы данных

        columns : iterable
            Список из параметров мероприятия

        Returns
        -------
        Event : Объект Event
        """
        # FIXME отладить работу
        event_dict = {}
        for i, tag in enumerate(columns):
            event_dict[tag] = data[tag]
        return cls(**event_dict)


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
            or (
                event.to_date is not None and event.to_date - event.from_date > two_days
            )
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

    return [
        Event.from_escraper(event) for event in events if event.is_registration_open
    ]


@catch_exceptions()
def _get_event(
    parser: escraper.parsers.base.BaseParser, *args, **kwargs
) -> List[Event]:
    event = parser.get_event(*args, **kwargs)

    return Event.from_escraper(event)


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
    events = timepad_others_organizations(days) + radario_others_organizations(days) \
             + ticketscloud_others_organizations(days)

    if date.today().weekday() == 0:
        events += vk_others_organizations(days)
    return events


def timepad_others_organizations(days: int) -> List[Event]:
    return get_timepad_events(
        days,
        TIMEPAD_OTHERS_PARAMS.copy(),
        events_filter=not_approved_organization_filter,
    )


def radario_others_organizations(days: int) -> List[Event]:
    return get_radario_events(days)


def ticketscloud_others_organizations(days: int) -> List[Event]:
    return get_ticketscloud_events(days)


def vk_others_organizations(days: int) -> List[Event]:
    return get_vk_events(days)


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
    event_ids = set()
    new_events = list()
    count = 0
    new_count = 1
    while new_count > 0:
        request_params["skip"] = count

        _new = _get_events(
            timepad_parser,
            request_params=request_params,
            tags=ALL_EVENT_TAGS,
        )
        new = [i for i in _new if i.event_id not in event_ids]
        event_ids.update([i.event_id for i in _new])

        new_count = len(new)

        new_events += new
        count += new_count

        time.sleep(1)

    if events_filter:
        new_events = events_filter(new_events)

    return new_events


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

    return new_events

def get_ticketscloud_events(
    days: int, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:

    new_events = _get_events(ticketscloud_parser, org_ids=TICKETSCLOUD_ORG_IDS)

    if events_filter:
        new_events = events_filter(new_events)

    return new_events


def get_vk_events(
    days: int = None, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:
    new_events = _get_events(vk_parser, days=days)
    if events_filter:
        new_events = events_filter(new_events)
    print(new_events)
    return new_events

def from_url(event_url):
    for parser_base_url, parser in PARSER_URLS.items():
        if parser_base_url in event_url:
            return _get_event(parser, event_url=event_url)
