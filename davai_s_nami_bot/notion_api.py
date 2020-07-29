import datetime
from datetime import date
import os
import time
from functools import partial

import requests

from notion.client import NotionClient


TAGS_TO_NOTION = [
    "id",
    "title",
    "category",
    "url",
    "date_from",
]
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


def add_events(events, explored_date, log=None):
    for event in events:

        row = table1.collection.add_row()

        for tag in TAGS_TO_NOTION:
            set_property(
                row=row,
                property_name=tag,
                value=getattr(event, tag),
                log=log,
            )

        # event not contain explored_date field
        set_property(
            row=row,
            property_name="explored_date",
            value=explored_date,
            log=log,
        )


def remove_blank_rows(log=None):
    rows = (
        list(table1.collection.get_rows())
        + list(table2.collection.get_rows())
        + list(table3.collection.get_rows())
    )

    for row in rows:
        if row.get_property("id") is None:
            remove_row(row, log=log)


def remove_old_events(removing_ids, msk_date, log=None):
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
            if row.get_property("id") in removing_ids:
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
    setattr(row, property_name, value)


@connection_wrapper
def remove_row(row):
    row.remove()


def move_row(row, to_table, log=None):
    new_row = to_table.collection.add_row()

    for tag in TAGS_TO_NOTION + ["explored_date"]:
        set_property(new_row, tag, row.get_property(tag), log=log)

    remove_row(row, log=log)


def next_event_id_to_channel():
    """
    Getting next event id from table 3 (from up to down).
    """
    rows = table3.collection.get_rows()
    event_id = None

    for row in rows:
        if not row.is_published:
            event_id = row.get_property("id")
            row.is_published = True
            break

    return event_id


def not_published_count():
    count = 0

    for row in table3.collection.get_rows():
        count += not row.is_published

    return count


def events_count():
    count = 0

    for table in [table1, table2, table3]:
        count += len(table.collection.get_rows())

    return count


def update_table_views():
    # 💫 some magic 💫
    # (see issue https://github.com/jamalex/notion-py/issues/92)
    for t in [table1, table2, table3]:
        print(t.collection.parent.views)
