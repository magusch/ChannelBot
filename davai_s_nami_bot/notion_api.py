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

notion_client = NotionClient(token_v2=NOTION_TOKEN_V2, start_monitoring=True, monitor=True)
table1 = notion_client.get_collection_view(NOTION_TABLE1_URL)
table2 = notion_client.get_collection_view(NOTION_TABLE2_URL)
table3 = notion_client.get_collection_view(NOTION_TABLE3_URL)

# 💫 some magic 💫
# (see issue https://github.com/jamalex/notion-py/issues/92)
for t in [table1, table2, table3]:
    print(t.collection.parent.views)


def add_events(events, existing_event_ids, explored_date):
    for event in events:

        if event.id in existing_event_ids:
            continue

        row = table1.collection.add_row()

        for tag in TAGS_TO_NOTION:
            set_property(
                row=row,
                property_name=tag,
                value=getattr(event, tag),
            )

        # event not contain explored_date field
        set_property(
            row=row,
            property_name="explored_date",
            value=explored_date,
        )


def remove_blank_rows():
    rows = (
        list(table1.collection.get_rows())
        + list(table2.collection.get_rows())
        + list(table3.collection.get_rows())
    )

    for row in rows:
        if row.get_property("id") is None:
            row.remove()


def remove_old_events(utc_date, msk_date):
    """
    Removing events:
        - from table 1, where explored date > 2 days ago
        - from table 2, where explored date > 7 days ago
        - from tables 1, 2, 3, where date_from < today
    """
    remove_blank_rows()

    tables = (table1, table2, table3)
    check_funcs = (
        partial(check_for_move_to_table2, date=msk_date, days=2),
        partial(check_explored_date, date=msk_date, days=7),
        None,
    )

    for table, check_func in zip(tables, check_funcs):

        for row in table.collection.get_rows():
            if in_past(row, target=utc_date):
                remove_row(row)

            elif check_func:
                check_func(row)


def in_past(record, target):
    return record.Date_from.start < target


def check_for_move_to_table2(record, date, days=None):
    if record.explored_date.start + datetime.timedelta(days=days) < date:
        move_row(record, table2)


def check_explored_date(record, date, days=None):
    if record.explored_date.start + datetime.timedelta(days=days) < date:
        remove_row(record)


def move_approved():
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
            move_row(row, table3)


def set_property(row, property_name, value):
    while True:
        try:
            setattr(row, property_name, value)
            break
        except requests.exceptions.HTTPError:
            Warning("Exception while inset to notion table. Retry...")


def remove_row(row):
    while True:
        try:
            row.remove()
            break
        except requests.exceptions.HTTPError:
            Warning("Exception while removing row. Retry...")


def move_row(row, to_table):
    new_row = to_table.collection.add_row()

    for tag in TAGS_TO_NOTION + ["explored_date"]:
        while True:
            try:
                setattr(new_row, tag, row.get_property(tag))
                break
            except requests.exceptions.HTTPError:
                Warning("Exception while moving row. Retry...")

    remove_row(row)


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
