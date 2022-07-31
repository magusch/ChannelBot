import os, datetime
import pytz
from typing import Any, List

import psycopg2
import requests
import pandas as pd


from .events import Event
from .logger import catch_exceptions, get_logger
from . import database
from . import clients


DEFAULT_UPDATING_STRFTIME = "00:00"

log = get_logger(__file__)


def next_event_to_channel():
    """
    Первое подходящее мероприятие из таблицы 3 для постинга в канал.

    Критерии поиска мероприятия:
    - Поиск происходит от по возрастанию значения `queue`
    - Значение поля `status` равное `ReadyToPost`
    - Наличие значения в поле `post_date` (равное текущему времени)
    """
    events = database.get_ready_to_post(table="events_events2post")

    event = Event.from_database(
        events[events["status"] == "ReadyToPost"].sort_values("queue").iloc[0, :]
    )
    database.set_status(
        table="events_events2post", event_id=event.event_id, status="Posted"
    )

    return event


def get_new_events(events: List[Event]) -> List[Event]:
    all_events = database.get_from_all_tables()

    new_ids = set([i.event_id for i in events]) - set(all_events["event_id"])

    return [i for i in set(events) if i.event_id in new_ids]


def not_published_count():
    events = database.get_all(table="events_events2post")

    return len(events[events["status"] == "ReadyToPost"])


def events_count():
    count = 0

    conn, cursor = get_db_connection()

    for table in (1, 2, 3):
        tablename = tables[table]
        script = f"SELECT count(*) FROM {tablename}"
        cursor.execute(script)
        count += cursor.fetchone()[0]

    cursor.close()
    return count


columns_for_posting_time = ["post_date", "title", "event_id"]


def next_posting_time(reference):
    all_events = database.get_ready_to_post(table="events_events2post")

    events_to_post = all_events[all_events["post_date"] >= reference]


    if pd.isnull(events_to_post["post_date"]).any():
        log.warn("Some events have not posting datetime.")
        events_to_post = events_to_post[~pd.isnull(events_to_post["post_date"])]

    if len(events_to_post) == 0:
        return None
    #TODO: Not sure this is good logic, to sort by post_date and get post_time, but post first by queue
    return events_to_post.sort_values("post_date")["post_date"].iloc[0].to_pydatetime()


def next_updating_time(reference):
    hour, minute = DEFAULT_UPDATING_STRFTIME.split(":")
    hour, minute = int(hour), int(minute)
    update_time = reference.replace(
        hour=hour, minute=minute
    )

    if reference.hour > hour or (
            reference.hour == hour and reference.minute > minute
    ):
        update_time += datetime.timedelta(days=1)

    return update_time


def next_task_time(msk_today):
    task_time = None
    posting_time = next_posting_time(reference=msk_today)
    update_time = next_updating_time(reference=msk_today)

    if posting_time is None and update_time is None:
        # something bad happening
        raise ValueError("Don't found event for posting and updating time!")

    if posting_time is None:
        log.warning("Don't event for posting! Continue with updating time.")
        task_time = update_time

    elif update_time is None:
        log.warning("Don't found updating time! Continue with posting time.")
        task_time = posting_time

    elif update_time - msk_today < posting_time - msk_today:
        task_time = update_time

    else:
        task_time = posting_time

    return task_time
