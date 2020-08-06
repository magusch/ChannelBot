import datetime
from datetime import date
from collections import namedtuple
import os
import time
from functools import partial

import requests

from notion.client import NotionClient

from . import posting


TAGS_TO_NOTION = {
    "Title": posting.parse_title,
    "Post": posting.parse_post,
    "URL": posting.parse_url,
    "From_date": posting.parse_from_date,
    "Event_id": posting.parse_event_id,
    "Image": posting.parse_image,
}
NOTION_TOKEN_V2 = os.environ.get("NOTION_TOKEN_V2")
NOTION_TABLE1_URL = os.environ.get("NOTION_TABLE1_URL")
NOTION_TABLE2_URL = os.environ.get("NOTION_TABLE2_URL")
NOTION_TABLE3_URL = os.environ.get("NOTION_TABLE3_URL")
MAX_NUMBER_CONNECTION_ATTEMPTS = 10

notion_client = NotionClient(token_v2=NOTION_TOKEN_V2)
table1 = notion_client.get_collection_view(NOTION_TABLE1_URL)
table2 = notion_client.get_collection_view(NOTION_TABLE2_URL)
table3 = notion_client.get_collection_view(NOTION_TABLE3_URL)


def connection_wrapper(func):

    def wrapper(*args, log=None, **kwargs):
        attempts_count = 0
        while True:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempts_count == MAX_NUMBER_CONNECTION_ATTEMPTS:
                    raise e

                log.warning(f"Retry (raised exception):\n", exc_info=True)
                attempts_count += 1

    return wrapper


def add_events(events, explored_date, table=None, log=None):
    table = table or table1
    table_name = table.collection.name

    for event in events:

        row = table.collection.add_row(update_views=False)

        for tag, parse_func in TAGS_TO_NOTION.items():
            set_property(
                row=row,
                property_name=tag,
                value=parse_func(event),
                log=log,
            )

        # event not contain "Explored date" and "Status" fields
        set_property(
            row=row,
            property_name="Explored date",
            value=explored_date,
            log=log,
        )

        # status only in table3
        if table_name == "Таблица 3":
            set_property(
                row=row,
                property_name="Status",
                value="Ready to post",
                log=log,
            )


def remove_blank_rows(log=None):
    rows = (
        list(table1.collection.get_rows())
        + list(table2.collection.get_rows())
        + list(table3.collection.get_rows())
    )

    for row in rows:
        if row.get_property("Event_id") is None:
            remove_row(row, log=log)


def remove_old_events(msk_date, log=None):
    """
    Removing events:
        - from table 1, where explored date > 2 days ago
        - from table 2, where explored date > 7 days ago
        - from tables 1, 2, 3, where date_from < today
    """
    remove_blank_rows(log=log)

    tables = (table1, table2, table3)
    check_funcs = (
        partial(check_for_move_to_table2, date=msk_date, days=2, log=log),
        partial(check_explored_date, date=msk_date, days=7, log=log),
        None,
    )

    for table, check_func in zip(tables, check_funcs):

        for row in table.collection.get_rows():
            if row.get_property("From_date").start < msk_date:
                remove_row(row, log=log)

            elif check_func:
                check_func(row, log=log)


def in_past(record, target):
    return record.Date_from.start < target


def check_for_move_to_table2(record, date, days=None, log=None):
    if record.explored_date.start + datetime.timedelta(days=days) < date:
        move_row(record, table2, log=log)


def check_explored_date(record, date, days=None, log=None):
    if record.explored_date.start + datetime.timedelta(days=days) < date:
        remove_row(record, log=log)


def move_approved(log=None):
    """
    Moving all approved events (with selected checkbox Approved)
    from table1 and table2 to table3.
    """
    rows = (
        list(table1.collection.get_rows())
        + list(table2.collection.get_rows())
    )

    for row in rows:
        if row.Approved:
            move_row(row, table3, log=log)


@connection_wrapper
def set_property(row, property_name, value):
    row.set_property(property_name, value)


@connection_wrapper
def remove_row(row):
    row.remove()


def move_row(row, to_table, log=None):
    if to_table.collection.name == "Таблица 3":
        # add at the end table
        new_row = to_table.collection.add_row()
        set_property(new_row, "status", "Ready to post", log=log)
    else:
        new_row = to_table.collection.add_row(update_views=False)

    for tag in list(TAGS_TO_NOTION.keys()) + ["Explored date"]:
        set_property(new_row, tag, row.get_property(tag), log=log)

    remove_row(row, log=log)


def next_event_to_channel():
    """
    Getting next event (namedtuple) from table 3 (from up to down).
    """
    rows = table3.collection.get_rows()
    event = None

    for row in rows:
        if row.status != "Posted":
            if row.status == "Ready to post":
                event = namedtuple("event", TAGS_TO_NOTION.keys())(
                    **{tag: row.get_property(tag) for tag in TAGS_TO_NOTION.keys()}
                )
                set_property(row, "status", "Posted")

            elif row.status == "Ready to skiped posting time":
                pass

            else:
                raise ValueError(f"Unavailable posting status: {row.status}")

            break

    return event


def get_new_events(events):
    existing_ids = list()
    for table in [table1, table2, table3]:
        for row in table.collection.get_rows():
            existing_ids.append(row.get_property("Event_id"))

    new_events = list()
    for event in events:
        if event.id not in existing_ids:
            new_events.append(event)

    return new_events

def not_published_count():
    count = 0

    for row in table3.collection.get_rows():
        count += row.status != "Posted"

    return count


def events_count():
    count = 0

    for table in [table1, table2, table3]:
        count += len(table.collection.get_rows())

    return count


def update_table_views():
    # 💫 some magic 💫
    # WARNING: if running background, need `> /dev/null`
    # (see issue https://github.com/jamalex/notion-py/issues/92)
    for t in [table1, table2, table3]:
        print(t.collection.parent.views)
