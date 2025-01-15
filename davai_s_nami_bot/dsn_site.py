import datetime
from typing import Any, List

import pandas as pd


from .events import Event
from .logger import catch_exceptions, get_logger
from . import database
from . import crud


DEFAULT_UPDATING_STRFTIME = "00:00"

log = get_logger(__file__)


def next_event_to_channel():
    """
    The first event from event2post table for posting

    Event search criteria:
    - Field `status` has `ReadyToPost` value
    - Datetime now is similar to `post_date`
    """
    events = database.get_event_to_post_now(table="events_events2post")

    if events is None or events.empty:
        event = None
    else:
        filtered_events = events[events["status"] == "ReadyToPost"].sort_values("queue")

        if not filtered_events.empty:
            event = Event.from_database(
                filtered_events.iloc[0, :]
            )
            crud.set_status(
                event_id=event.event_id, status="Posted"
            )
        else:
            event = None

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
    if len(all_events) == 0:
        return None

    all_events["post_date"] = pd.to_datetime(all_events["post_date"]).dt.tz_convert(reference.tzinfo)

    events_to_post = all_events[all_events["post_date"] >= reference]


    if pd.isnull(events_to_post["post_date"]).any():
        log.warn("Some events have not posting datetime.")
        events_to_post = events_to_post[~pd.isnull(events_to_post["post_date"])]

    if len(events_to_post) == 0:
        return None
    #TODO: Not sure this is good logic, to sort by post_date and get post_time, but post first by queue
    return events_to_post.sort_values("post_date")["post_date"].iloc[0]


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
