from datetime import date
import os
import time
from multiprocessing import Lock

from notion.client import NotionClient


TAGS_TO_NOTION = [
    "id",
    "title",
    "category",
    "poster_imag",
    "url",
    "date_from",
]
NOTION_TOKEN_V2 = os.environ.get("NOTION_TOKEN_V2")
NOTION_ALL_EVENTS_TABLE_URL = os.environ.get("NOTION_ALL_EVENTS_TABLE_URL")
NOTION_TO_CHANNEL_TABLE_URL = os.environ.get("NOTION_TO_CHANNEL_TABLE_URL")

notion_client = NotionClient(token_v2=NOTION_TOKEN_V2, start_monitoring=True, monitor=True)
all_events_table = notion_client.get_collection_view(NOTION_ALL_EVENTS_TABLE_URL)
to_channel_table = notion_client.get_collection_view(NOTION_TO_CHANNEL_TABLE_URL)

# 💫 some magic 💫
# (see issue https://github.com/jamalex/notion-py/issues/92)
print(all_events_table.collection.parent.views)
print(to_channel_table.collection.parent.views)

mutex = Lock()


def add_event_to_channel_table(record):
    row = to_channel_table.collection.add_row()
    for tag in TAGS_TO_NOTION:
        setattr(row, tag, record.get_property(tag))


def row_callback(record, changes):
    with mutex:
        is_approved = record.Approved
        record.Approved = False

    if is_approved:
        add_event_to_channel_table(record)
        record.remove()


def add_events(events, existing_event_ids):
    for event in events:

        if event.id in existing_event_ids:
            continue

        row = all_events_table.collection.add_row()
        for tag in TAGS_TO_NOTION:
            setattr(row, tag, getattr(event, tag))

        row.add_callback(row_callback)


def remove_blank_rows():
    rows = all_events_table.collection.get_rows()

    for row in rows:
        if row.get_property("id") is None:
            row.remove()


def remove_old_events(date):
    """
    Removing events where date < current date.
    """
    remove_blank_rows()

    for row in all_events_table.collection.get_rows():
        if row.Date_from.start < date:
            row.remove()
            time.sleep(0.5)  # to avoid 504 http error
