import time
from collections import namedtuple
from datetime import date, datetime, timedelta

from typing import Any, Callable, Dict, List, NamedTuple

import escraper
from escraper.parsers import ALL_EVENT_TAGS, Radario, Timepad, Ticketscloud, VK, QTickets, MTS, Culture

from . import utils
from .logger import catch_exceptions

from .dsn_site_session import place_address

from .helper.dsn_parameters import dsn_parameters


STARTS_AT_MIN = "{year_month_day}T10:00:00"
STARTS_AT_MAX = "{year_month_day}T23:59:00"

MAX_NEXT_DAYS = 30
two_days = timedelta(days=2)

## PARSERS
timepad_parser = Timepad()
radario_parser = Radario()
ticketscloud_parser = Ticketscloud()
vk_parser = VK()
qt_parser = QTickets()
mts_parser = MTS()
culture_parser = Culture()

PARSER_URLS = {
    'timepad.ru': timepad_parser, 'vk.': vk_parser,
    'ticketscloud.': ticketscloud_parser, 'radario.ru': radario_parser,
    'qtickets.events': qt_parser, 'live.mts.ru': mts_parser,
    'culture.ru': culture_parser
}


def get_city_param():
    cities = dsn_parameters.site_parameters('city')

    if cities:
        return cities[0]
    else:
        return 'spb'


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
        address_line = f"[{event.place_name}, {event.adress}](https://2gis.ru/{get_city_param()}/search/{event.adress})"

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


def _category(event: NamedTuple):
    return event.category

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
        category=_category,
        address=_address,
    )
    _tags = list(_escraper_event_parsers)

    _additional_tags = [
        'id', 'queue', 'prepared_text', 'status', 'post_url', 
        'place_id', 'is_ready', 'explored_date', 'post_date', 
        'main_category_id'
    ]

    _all_tags = _tags + _additional_tags

    def __new__(cls, **kwargs):
        # Создаем namedtuple с основными полями
        base_fields = {k: v for k, v in kwargs.items() if k in cls._tags}
        base_event = namedtuple("event", cls._tags)(**base_fields)
        
        # Создаем экземпляр класса
        instance = super().__new__(cls)
        instance._base = base_event
        instance._additional = {}
        
        # Сохраняем дополнительные поля
        for tag in cls._additional_tags:
            if tag in kwargs:
                instance._additional[tag] = kwargs[tag]
                
        return instance
    
    def __getattr__(self, name):
        # Пробуем получить атрибут из базового namedtuple
        try:
            return getattr(self._base, name)
        except AttributeError:
            # Если атрибут не найден в базовом namedtuple, пробуем получить из дополнительных полей
            if name in self._additional:
                return self._additional[name]
            raise
    
    def _asdict(self):
        """Возвращает словарь с основными полями (для совместимости с namedtuple)"""
        return self._base._asdict()
    
    def to_dict(self):
        """Преобразует Event в словарь для сохранения в базу данных"""
        result = self._asdict()
        # Добавляем дополнительные поля
        result.update(self._additional)
        return result

    @classmethod
    def from_escraper(cls, event: NamedTuple):
        return cls(
            **{
                tag: parse_func(event)
                for tag, parse_func in cls._escraper_event_parsers.items()
            }
        )

    @classmethod
    def from_database(cls, data, columns=None):
        """
        Создание объекта `Event` из записи базы данных.

        Parameters
        ----------
        data : tuple or dict or SQLAlchemy model
            Строчка данных из базы данных, словарь с данными или объект SQLAlchemy

        columns : iterable
            Список из параметров мероприятия

        Returns
        -------
        Event : Объект Event
        """
        # Если columns не указан, используем все теги
        if columns is None:
            columns = cls._all_tags
            
        event_dict = {}
        
        # Обработка SQLAlchemy объекта
        if hasattr(data, '__table__'):
            for column in data.__table__.columns:
                value = getattr(data, column.name)
                # Преобразуем типы данных, если необходимо
                if column.name in ['from_date', 'to_date', 'explored_date', 'post_date'] and value is not None:
                    if isinstance(value, str):
                        try:
                            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        except ValueError:
                            value = datetime.today()
                event_dict[column.name] = value
                
        # Обработка словаря
        elif isinstance(data, dict):
            for tag in columns:
                if tag in data:
                    value = data[tag]
                    # Преобразуем типы данных, если необходимо
                    if tag in ['from_date', 'to_date', 'explored_date', 'post_date'] and value is not None:
                        if isinstance(value, str):
                            try:
                                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            except ValueError:
                                value = datetime.today()
                    event_dict[tag] = value
                else:
                    # Устанавливаем значения по умолчанию
                    if 'date' in tag:
                        event_dict[tag] = datetime.today()
                    elif tag in ['id', 'queue', 'place_id', 'main_category_id']:
                        event_dict[tag] = None
                    elif tag in ['is_ready']:
                        event_dict[tag] = False
                    else:
                        event_dict[tag] = ''
                        
        # Обработка кортежа или другой последовательности
        else:
            for i, tag in enumerate(columns):
                if i < len(data):
                    value = data[i]
                    # Преобразуем типы данных, если необходимо
                    if tag in ['from_date', 'to_date', 'explored_date', 'post_date'] and value is not None:
                        if isinstance(value, str):
                            try:
                                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            except ValueError:
                                value = datetime.today()
                    event_dict[tag] = value
                else:
                    # Устанавливаем значения по умолчанию
                    if 'date' in tag:
                        event_dict[tag] = datetime.today()
                    elif tag in ['id', 'queue', 'place_id', 'main_category_id']:
                        event_dict[tag] = None
                    elif tag in ['is_ready']:
                        event_dict[tag] = False
                    else:
                        event_dict[tag] = ''
        
        return cls(**event_dict)

    @classmethod
    def from_dict(cls, data, columns=None):
        """
        Создание объекта `Event` из словаря.

        Parameters
        ----------
        data : dict
            Словарь с данными

        columns : iterable
            Список из параметров мероприятия

        Returns
        -------
        Event : Объект Event
        """
        # Если columns не указан, используем все теги
        if columns is None:
            columns = cls._all_tags
            
        event_dict = {}
        
        for tag in columns:
            if tag in data:
                # Преобразуем типы данных, если необходимо
                value = data[tag]
                
                # Обработка специальных типов данных
                if tag in ['from_date', 'to_date', 'explored_date', 'post_date'] and value is not None:
                    if isinstance(value, str):
                        try:
                            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        except ValueError:
                            value = datetime.today()
                
                event_dict[tag] = value
            else:
                # Устанавливаем значения по умолчанию
                if 'date' in tag:
                    event_dict[tag] = datetime.today()
                elif tag in ['id', 'queue', 'place_id', 'main_category_id']:
                    event_dict[tag] = None
                elif tag in ['is_ready']:
                    event_dict[tag] = False
                else:
                    event_dict[tag] = ''
        
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
    weekday = date.today().weekday()
    if weekday % 2 == 0:
        return get_timepad_events(
            days,
            timepad_request_params(approved=1),

        )
    else:
        return []


def from_not_approved_organizations(days: int) -> List[Event]:
    events = []

    function_list_even = [
        timepad_others_organizations,
        radario_others_organizations,
    ]

    function_list_odd = [
        qtickets_others_organizations,
        ticketscloud_others_organizations
    ]

    weekday = date.today().weekday()

    if weekday % 2 == 1:
        for func in function_list_odd:
            try:
                events += func(days*2)
            except Exception as e:
                print(f"An error occurred in {func.__name__}: {e}")
    else:
        for func in function_list_even:
            try:
                events += func(days)
            except Exception as e:
                print(f"An error occurred in {func.__name__}: {e}")

    if weekday == 6:
        try:
            events += vk_others_organizations(days)
        except Exception as e:
            print(f"An error occurred in vk_others_organizations: {e}")

    if weekday == 0 or weekday == 4:
        try:
            events += mts_others_organization(days)
        except Exception as e:
            print(f"An error occurred in mts_others_organization: {e}")
    elif weekday == 2 or weekday == 5:
        try:
            events += culture_others_organizations(days)
        except Exception as e:
            print(f"An error occurred in culture_organizations: {e}")

    return events


def timepad_others_organizations(days: int) -> List[Event]:
    timepad_others_params = timepad_request_params()
    return get_timepad_events(
        days,
        timepad_others_params,
        events_filter=not_approved_organization_filter,
    )


def timepad_request_params(approved: bool = False) -> Dict:
    timepad_params = dsn_parameters.read_param('timepad')

    timepad_others_params = dict(
        limit=100,
        cities="Санкт-Петербург",
        moderation_statuses="featured, shown",
    )

    if timepad_params:
        if not approved:
            timepad_others_params['price_max'] = 5000
            if dsn_parameters.read_param('timepad')['city']:
                timepad_others_params["cities"] = dsn_parameters.read_param('timepad')['city'][0]
            if dsn_parameters.read_param('timepad')['price_max']:
                timepad_others_params["price_max"] = dsn_parameters.read_param('timepad')['price_max'][0]

            timepad_others_params["organization_ids_exclude"] = (
                    ", ".join(
                        timepad_params['approved_organization'] + timepad_params['boring_organization'])
                )
            timepad_others_params["category_ids_exclude"] = ", ".join(timepad_params['exclude_categories'])
            timepad_others_params["keywords_exclude"] = ", ".join(timepad_params['bad_keywords'])
        else:
            timepad_others_params['organization_ids'] = timepad_params['approved_organization']
    elif approved:
        timepad_others_params['organization_ids'] = []

    if timepad_others_params['limit']>100:
        timepad_others_params['limit'] = 100

    return timepad_others_params


def radario_others_organizations(days: int) -> List[Event]:
    return get_radario_events(days)


def ticketscloud_others_organizations(days: int) -> List[Event]:
    return get_ticketscloud_events(days)


def vk_others_organizations(days: int) -> List[Event]:
    return get_vk_events(days)


def qtickets_others_organizations(days: int) -> List[Event]:
    return get_qtickets_events(days)


def mts_others_organization(days: int) -> List[Event]:
    return get_mts_events(days)


def culture_others_organizations(days: int) -> List[Event]:
    return get_culture_events(days)


def get_timepad_events(
    days: int,
    request_params: Dict[str, Any] = None,
    events_filter: Callable[[List[Event]], List[Event]] = None,
    with_online: bool = False,
) -> List[Event]:
    """
    Getting events.
    """
    if days > MAX_NEXT_DAYS:
        raise ValueError(
            f"Too much days for getting events: {days}."
            f"Maximum is {MAX_NEXT_DAYS} days."
        )
    today = date.today() + timedelta(days=1)

    if request_params is None:
        request_params = timepad_request_params()

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

    radario_city = 'spb'

    radario_cities = dsn_parameters.read_param('radario').get('city_id')
    if radario_cities:
        radario_city = radario_cities[0]

    request_params = {
        "from": date_from,
        "to": date_to,
        "category": category,
        "city": radario_city,
    }

    new_events = _get_events(radario_parser, request_params=request_params)

    if events_filter:
        new_events = events_filter(new_events)

    return new_events

def get_ticketscloud_events(
    days: int, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:
    tc_org_ids = dsn_parameters.read_param('ticketscloud')['org_id']
    new_events = _get_events(ticketscloud_parser, org_ids=tc_org_ids, city=get_city_param(), tags=ALL_EVENT_TAGS)

    if events_filter:
        new_events = events_filter(new_events)

    return new_events


def get_vk_events(
    days: int = None, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:

    vk_city_id = '2'
    vk_city = 'Санкт-Петербург'

    vk_param = dsn_parameters.read_param('vk')
    if vk_param:
        if vk_param.get('city_id'):
            vk_city_id = vk_param.get('city_id')[0]

        if vk_param.get('city'):
            vk_city = vk_param.get('city')[0]

    request_params = {
        'days': days * 2,
        'city_id': vk_city_id,
        'city': vk_city
    }

    new_events = _get_events(vk_parser, request_params=request_params)
    if events_filter:
        new_events = events_filter(new_events)
    return new_events


def get_qtickets_events(
    days: int = None, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:

    qt_city = 'spb'

    qt_cities = dsn_parameters.read_param('qtickets').get('city_id')
    if qt_cities:
        qt_city = qt_cities[0]

    request_params = {
        "days": days,
        "city": qt_city
    }

    new_events = _get_events(qt_parser, request_params=request_params, tags=ALL_EVENT_TAGS,)
    if events_filter:
        new_events = events_filter(new_events)
    return new_events


def get_mts_events(
    days: int = None, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:
    mts_city = 'sankt-peterburg'

    mts_cities = dsn_parameters.read_param('mts').get('city')
    if mts_cities:
        mts_city = mts_cities[0]

    categories = ["ribbon", "concerts", "theater", "musicals", "show", "exhibitions", "sport"]
    request_params = {
            "city": mts_city,
            "categories": categories,
            "days": days
    }

    new_events = _get_events(mts_parser, request_params=request_params, tags=ALL_EVENT_TAGS,)

    if events_filter:
        new_events = events_filter(new_events)
    return new_events


def get_culture_events(
    days: int = None, events_filter: Callable[[List[Event]], List[Event]] = None
) -> List[Event]:

    culture_city = 'sankt-peterburg'

    culture_cities = dsn_parameters.read_param('culture').get('city')
    if culture_cities:
        culture_city = culture_cities[0]

    #categories = ["ribbon", "concerts", "theater", "musicals", "show", "exhibitions", "sport"]
    request_params = {
            "city": culture_city,
            "days": days
    }

    new_events = _get_events(culture_parser, request_params=request_params, tags=ALL_EVENT_TAGS,)

    if events_filter:
        new_events = events_filter(new_events)
    return new_events


escraper_sites = {
    'timepad':      get_timepad_events,
    'radario':      get_radario_events,
    'ticketscloud': get_ticketscloud_events,
    'vk':           get_vk_events,
    'qtickets':     get_qtickets_events,
    'mts':          get_mts_events,
    'culture':      get_culture_events
}


def from_url(event_url):
    for parser_base_url, parser in PARSER_URLS.items():
        if parser_base_url in event_url:
            return _get_event(parser, event_url=event_url)
    return None
