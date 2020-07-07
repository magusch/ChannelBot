from collections import Counter
from datetime import date, timedelta

from escraper.parsers import Timepad, ALL_EVENT_TAGS


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
    starts_at_min="{year_month_day}T00:00:00",
    starts_at_max="{year_month_day}T23:59:00",
    category_ids_exclude="217, 376, 379, 399, 453, 1315",
    cities="Санкт-Петербург",
    moderation_statuses="featured, shown",  # don't understand what is it
    keywords_exclude=", ".join(BAD_KEYWORDS),
)
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
        ):
            continue

        good_events.append(event)

    return good_events


def today(with_online=True):
    """
    Getting today's events.
    """
    request_params = TIMEPAD_PARAMS.copy()

    today = date.today()
    for tag in ["starts_at_min", "starts_at_max"]:
        request_params[tag] = request_params[tag].format(
            year_month_day=today.strftime("%Y-%m-%d")
        )

    if with_online:
        request_params["cities"] += ", Без города"

    # for getting all events (max limit 100)
    today_events = list()
    count = 0
    new_items = 1
    while new_items > 0:
        request_params["skip"] = count
        new = timepad_parser.get_events(
            request_params=request_params, tags=ALL_EVENT_TAGS
        )
        new_items = len(new)

        today_events += apply_events_filter(new)

        count += new_items

    return unique(today_events)  # checking for unique -- just in case


def unique(events):
    return set(events)
