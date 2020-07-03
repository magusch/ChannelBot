from collections import Counter
from datetime import date

from escraper.parsers import Timepad


TAGS_TO_DATABASE = [
    "id",
    "title",
    "category",
    "poster_imag",
    "url",
    "date",
]
TIMEPAD_PARAMS = dict(
    limit=100,
    price_max=500,
    starts_at_min="{year_month_day}T00:00:00",
    starts_at_max="{year_month_day}T23:59:00",
    category_ids_exclude="217, 376, 379, 399, 453, 1315",
    cities="Санкт-Петербург",
)
timepad_parser = Timepad()


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
            request_params=request_params, tags=TAGS_TO_DATABASE
        )
        new_items = len(new)

        # unmoderated events equals None
        today_events += [i for i in new if i is not None]

        count += new_items

    return unique(today_events)  # checking for unique -- just in case


def unique(events):
    """
    TODO
    """
    return events
