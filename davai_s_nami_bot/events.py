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
TIMEPAD_PARAMS = dict(
    limit=100,
    price_max=500,
    starts_at_min="{year_month_day}T11:00:00",
    starts_at_max="{year_month_day}T23:59:00",
    category_ids_exclude="217, 376, 379, 399, 453, 1315, 452, 382, 2335, 524, 462",
    cities="Санкт-Петербург",
    moderation_statuses="featured, shown",
    keywords_exclude=", ".join(BAD_KEYWORDS),
)
MAX_NEXT_DAYS = 30
two_days = timedelta(days=2)
timepad_parser = Timepad()


def apply_events_filter(events):
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
            or event.poster_imag==None
        ):
            continue

        good_events.append(event)

    return good_events


@connection_wrapper
def _get(*args, **kwargs):
    return timepad_parser.get_events(*args, **kwargs)


def next_days(days=1, with_online=True):
    """
    Getting events for next few days.
    """
    if days > MAX_NEXT_DAYS:
        raise ValueError(
            f"Too much days for getting events: {days}."
            f"Maximum is {MAX_NEXT_DAYS} days."
        )

    request_params = TIMEPAD_PARAMS.copy()

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

        new = _get(request_params=request_params, tags=ALL_EVENT_TAGS)
        new_items = len(new)

        today_events += apply_events_filter(new)

        count += new_items

        time.sleep(1)

    return unique(today_events)  # checking for unique -- just in case


def unique(events):
    return set(events)
