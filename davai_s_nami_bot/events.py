import re, json
import time
from collections import namedtuple
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any, Callable, Dict, List, NamedTuple

import escraper
from escraper.parsers import ALL_EVENT_TAGS, Radario, Timepad, Ticketscloud, VK, QTickets

from .parameters_for_channel import *
from . import utils
from .logger import catch_exceptions

from .dsn_site_session import place_address



BAD_KEYWORDS = parameters_list_ids('timepad', 'bad_keywords')

APPROVED_ORGANIZATIONS = parameters_list_ids('timepad', 'approved_organization')
BORING_ORGANIZATIONS = parameters_list_ids('timepad', 'boring_organization')

CATEGORY_IDS_EXCLUDE = parameters_list_ids('timepad', 'exclude_categories')
STARTS_AT_MIN = "{year_month_day}T10:00:00"
STARTS_AT_MAX = "{year_month_day}T23:59:00"
FINISH_LINK = parameters_list_ids('dsn_site', 'finish_link')[0]

cities = parameters_list_ids('dsn_site', 'city')
if cities:
    CITY = cities[0]
else:
    CITY = 'spb'

timepad_city = "Санкт-Петербург"
RADARIO_CITY = 'spb'
QT_CITY = 'spb'
VK_CITY_ID = '2'
VK_CITY = 'Санкт-Петербург'

if CITY != 'spb':
    timepad_cities = parameters_list_ids('timepad', 'city')
    if timepad_cities:
        timepad_city = timepad_cities[0]

    radario_cities = parameters_list_ids('radario', 'city')
    if radario_cities:
        RADARIO_CITY = radario_cities[0]

    qt_cities = parameters_list_ids('qtickets', 'city')
    if qt_cities:
        QT_CITY = qt_cities[0]

    vk_cities_id = parameters_list_ids('vk', 'city_id')
    if vk_cities_id:
        VK_CITY_ID = vk_cities_id[0]

    vk_cities = parameters_list_ids('vk', 'city')
    if vk_cities:
        VK_CITY = vk_cities[0]
    else:
        VK_CITY = ''





TIMEPAD_APPROVED_PARAMS = dict(
    limit=100,
    cities=timepad_city,
    moderation_statuses="featured, shown",
    organization_ids=", ".join(APPROVED_ORGANIZATIONS),
)
TIMEPAD_OTHERS_PARAMS = dict(
    limit=100,
    cities=timepad_city,
    moderation_statuses="featured, shown",
    organization_ids_exclude=(
        ", ".join(APPROVED_ORGANIZATIONS) + ", " + ", ".join(BORING_ORGANIZATIONS)
    ),
    price_max=parameter_value('timepad', 'price_max'),
    category_ids_exclude=", ".join(CATEGORY_IDS_EXCLUDE),
    keywords_exclude=", ".join(BAD_KEYWORDS),
)
MAX_NEXT_DAYS = 30
two_days = timedelta(days=2)

TICKETSCLOUD_ORG_IDS = parameters_list_ids('ticketscloud', 'org_id')

## PARSERS
timepad_parser = Timepad()
radario_parser = Radario()
ticketscloud_parser = Ticketscloud()
vk_parser = VK()
qt_parser = QTickets()

PARSER_URLS = {
    'timepad.ru': timepad_parser, 'vk.': vk_parser,
    'ticketscloud.': ticketscloud_parser, 'radario.ru': radario_parser,
    'qtickets.events': qt_parser
}

## ESCRAPER EVENTS PARSERS
def _title(event: NamedTuple):
    return event.title.replace("`", r"\`").replace("_", r"\_").replace("*", r"\*")


def _full_text(event: NamedTuple):
    return event.full_text

def _post(event: NamedTuple):
    return event.post_text
    # title = _title(event)
    #
    # title = re.sub(r"[\"«](?=[^\ \.!\n])", "*«", title)
    # title = re.sub(r"[\"»](?=[^a-zA-Zа-яА-Я0-9]|$)", "»*", title)
    #
    # date_from_to = date_to_post(event.date_from, event.date_to)
    #
    #
    # # title_date = "{day} {month}".format(
    # #     day=event.date_from.day,
    # #     month=month_name(event.date_from),
    # # )
    # title_date = date_to_title(event.date_from, event.date_to)
    #
    # title = f"*{title_date}* {title}\n\n"
    #
    # post_text = (
    #     event.post_text.strip()
    #     .replace("`", r"\`")
    #     .replace("_", r"\_")
    #     .replace("*", r"\*")
    # )
    #
    # address_line = address_line_to_post(event)
    #
    # footer = (
    #     "\n\n"
    #     f"*Где:* {address_line}\n"
    #     f"*Когда:* {date_from_to}\n"
    #     f"*Вход:* [{event.price}]({event.url})\n"
    #     f"\n{FINISH_LINK}"
    # )
    #
    # return title + post_text + footer


def weekday_name(dt: datetime):
    return utils.WEEKNAMES[dt.weekday()]


def month_name(dt: datetime):
    return utils.MONTHNAMES[dt.month]


def date_to_title(date_from: datetime, date_to: datetime):
    title_date = ''
    if date_to is None:
        title_date = "{day} {month}".format(
            day=date_from.day,
            month=month_name(date_from),
        )
    elif date_from.month != date_to.month:
        title_date = "{day_s} {month_s} – {day_e} {month_e}".format(
            day_s=date_from.day,
            month_s=month_name(date_from),
            day_e=date_to.day,
            month_e=month_name(date_to)
        )
    elif date_to.day-date_from.day==1:
        title_date = "{day_s} и {day_e} {month_s}".format(
            day_s=date_from.day,
            month_s=month_name(date_from),
            day_e=date_to.day
        )
    elif date_from.day != date_to.day:
        title_date = "{day_s} – {day_e} {month_s}".format(
            day_s=date_from.day,
            month_s=month_name(date_from),
            day_e=date_to.day
        )
    else:
        title_date = "{day} {month}".format(
            day=date_from.day,
            month=month_name(date_from),
        )
    return title_date


def date_to_post(date_from: datetime, date_to: datetime):
    s_weekday = weekday_name(date_from)
    s_day = date_from.day
    s_month = month_name(date_from)
    s_hour = date_from.hour
    s_minute = date_from.minute

    if date_to is not None:
        e_weekday = weekday_name(date_to)
        e_day = date_to.day
        e_month = month_name(date_to)
        e_hour = date_to.hour
        e_minute = date_to.minute

        if s_day == e_day:
            start_format = f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}-"
            end_format = f"{e_hour:02}:{e_minute:02}"

        elif s_month!=e_month:
            start_format = f"{s_weekday}-{e_weekday}, {s_day} {s_month} - "
            end_format = f"{e_day} {e_month} {s_hour:02}:{s_minute:02}–{e_hour:02}:{e_minute:02}"
        else:
            # start_format = f"с {s_day} {s_month} {s_hour:02}:{s_minute:02} "
            # end_format = f"по {e_day} {e_month} {e_hour:02}:{e_minute:02}"
            start_format = f"{s_weekday}-{e_weekday}, {s_day}–{e_day} {s_month} {s_hour:02}:{s_minute:02}-"
            end_format = f"{e_hour:02}:{e_minute:02}"

    else:
        end_format = ""
        start_format = f"{s_weekday}, {s_day} {s_month} {s_hour:02}:{s_minute:02}"

    return start_format + end_format


def address_line_to_post(event):
    raw_address = f"{event.place_name}, {event.adress}"
    address = place_address(raw_address)

    address_line = None
    if address.status_code<300:
        address_dict = address.json()
        if address_dict['response_code']<400:
            address_line = address_dict["address_for_post"]

    if not address_line:
        address_line = f"[{event.place_name}, {event.adress}](https://2gis.ru/{CITY}/search/{event.adress})"

    return address_line


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
        full_text=_full_text,
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
    events = []

    function_list = [
        timepad_others_organizations,
        radario_others_organizations,
        ticketscloud_others_organizations,
    ]

    for func in function_list:
        try:
            events += func(days)
        except Exception as e:
            print(f"An error occurred in {func.__name__}: {e}")

    if date.today().weekday() == 0:
        try:
            events += vk_others_organizations(days)
        except Exception as e:
            print(f"An error occurred in vk_others_organizations: {e}")
    elif date.today().weekday() % 2 == 1:
        try:
            events += qtickets_others_organizations(days*2)
        except Exception as e:
            print(f"An error occurred in qtickets_others_organizations: {e}")

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

def qtickets_others_organizations(days: int) -> List[Event]:
    return get_qtickets_events(days)


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
        "city": RADARIO_CITY,
    }

    new_events = _get_events(radario_parser, request_params=request_params)

    if events_filter:
        new_events = events_filter(new_events)

    return new_events

def get_ticketscloud_events(
    days: int, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:

    new_events = _get_events(ticketscloud_parser, org_ids=TICKETSCLOUD_ORG_IDS, city=CITY)

    if events_filter:
        new_events = events_filter(new_events)

    return new_events


def get_vk_events(
    days: int = None, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:


    request_params = {
        'days': 15,
        'city_id': VK_CITY_ID,
        'city': VK_CITY
    }

    new_events = _get_events(vk_parser, request_params=request_params)
    if events_filter:
        new_events = events_filter(new_events)
    return new_events


def get_qtickets_events(
    days: int = None, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:

    request_params = {
        "days": days,
        "city": QT_CITY
    }

    new_events = _get_events(qt_parser, request_params=request_params)
    if events_filter:
        new_events = events_filter(new_events)
    return new_events

def from_url(event_url):
    for parser_base_url, parser in PARSER_URLS.items():
        if parser_base_url in event_url:
            return _get_event(parser, event_url=event_url)
