import time
from collections import Counter
from datetime import date, timedelta

from escraper.parsers import Timepad, ALL_EVENT_TAGS

from .notion_api import connection_wrapper


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
    "185394", #Арт-экспо выставки https://art-ekspo-vystavki.timepad.ru/
    "106118", #АНО «ЦДПО — «АЛЬФА-ДИАЛОГ»
    "212547", #Иерусалимская Сказка
    "146675", #Корни и Крылья https://korni-i-krylya.timepad.ru
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
TIMEPAD_APPROVED_PARAMS = dict(
    limit=100,
    starts_at_min="{year_month_day}T11:00:00",
    starts_at_max="{year_month_day}T23:59:00",
    cities="Санкт-Петербург",
    moderation_statuses="featured, shown",
    organization_ids=", ".join(APPROVED_ORGANIZATIONS),
)
TIMEPAD_OTHERS_PARAMS = dict(
    limit=100,
    starts_at_min="{year_month_day}T11:00:00",
    starts_at_max="{year_month_day}T23:59:00",
    cities="Санкт-Петербург",
    moderation_statuses="featured, shown",
    organization_ids_exclude=(
        ", ".join(APPROVED_ORGANIZATIONS)
        + ", " + ", ".join(BORING_ORGANIZATIONS)
    ),
    price_max=500,
    category_ids_exclude=", ".join(CATEGORY_IDS_EXCLUDE),
    keywords_exclude=", ".join(BAD_KEYWORDS),
)
MAX_NEXT_DAYS = 30
two_days = timedelta(days=2)
timepad_parser = Timepad()


def not_approved_organization_filter(events):
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
            or not event.is_registration_open
            or (event.date_to is not None and event.date_to - event.date_from > two_days)
            or event.poster_imag == None
        ):
            continue

        good_events.append(event)

    return good_events


def approved_organization_filter(events):
    """
    Remove events:
    - with closed registration
    """
    good_events = list()

    for event in events:
        if not event.is_registration_open:
            continue

        good_events.append(event)

    return good_events


@connection_wrapper
def _get(*args, **kwargs):
    return timepad_parser.get_events(*args, **kwargs)


def from_approved_organizations(days, log, **kwargs):
    """
    Getting events from approved organizations (see. APPROVED_ORGANIZATIONS).
    """
    return get_events(
        days,
        TIMEPAD_APPROVED_PARAMS,
        log,
        events_filter=approved_organization_filter,
        **kwargs,
    )


def from_not_approved_organizations(days, log, **kwargs):
    return get_events(
        days,
        TIMEPAD_OTHERS_PARAMS,
        log,
        events_filter=not_approved_organization_filter,
        **kwargs,
    )


def get_events(days, request_params, log, events_filter=None, with_online=True):
    """
    Getting events.
    """
    if days > MAX_NEXT_DAYS:
        raise ValueError(
            f"Too much days for getting events: {days}."
            f"Maximum is {MAX_NEXT_DAYS} days."
        )

    today = date.today()
    request_params["starts_at_min"] = request_params["starts_at_min"].format(
        year_month_day=today.strftime("%Y-%m-%d")
    )
    request_params["starts_at_max"] = request_params["starts_at_max"].format(
        year_month_day=(today + timedelta(days=days)).strftime("%Y-%m-%d")
    )

    if with_online:
        request_params["cities"] += ", Без города"

    # for getting all events (max limit 100)
    today_events = list()
    count = 0
    new_items = 1
    while new_items > 0:
        request_params["skip"] = count

        new = _get(request_params=request_params, tags=ALL_EVENT_TAGS, log=log)
        new_items = len(new)

        today_events += new
        count += new_items

        time.sleep(1)

    if events_filter:
        today_events = events_filter(today_events)

    return unique(today_events)  # checking for unique -- just in case


def unique(events):
    return set(events)
