from datetime import date

from escraper.parsers import Timepad

from .database import add2db


TIMEPAD_PARAMS = dict(
    limit=100,
    price_max=500,
    starts_at_min="{year_month_day}T00:00:00",
    starts_at_max="{year_month_day}T23:59:00",
    category_ids_exclude="217, 376, 379, 399, 453, 1315",
    cities="Без города, Санкт-Петербург",  # Без города == online
)
timepad_parser = Timepad()


def today():
    request_params = TIMEPAD_PARAMS.copy()

    today = date.today()
    for tag in ["starts_at_min", "starts_at_max"]:
        request_params[tag] = request_params[tag].format(
            year_month_day=today.strftime("%Y-%m-%d")
        )

    # for getting all events (max limit 100)
    today_events = list()
    count = -1
    new_items = 1
    while new_items > 0:
        request_params["skip"] = count + 1
        new = timepad_parser.get_events(request_params=request_params)
        new_items = len(new)
        today_events += new

        count += new_items

    return today_events


def update_database(events):
    # FIXME bad: add to database something return
    duplicated_event_ids = add2db(events)

    return duplicated_event_ids
