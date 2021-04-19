import os, datetime
import pytz
from typing import Any, List

import psycopg2
import requests
import pandas as pd
from fake_useragent import UserAgent

from .events import Event
from .logger import catch_exceptions, get_logger
from . import database
from . import clients


BASE_URL = "http://dsn.4geek.ru/"
CHECK_EVENT_STATUS_URL = BASE_URL + "events/check_event_status/"
MOVE_APPROVED_URL = BASE_URL + "events/move_approved_events/"
REMOVE_OLD_URL = BASE_URL + "events/remove_old_events/"
UPDATE_ALL_URL = BASE_URL + "events/update_all/"
FILL_EMPTY_POST_TIME_URL = BASE_URL + "events/fill_empty_post_time/"
CSRFTOKEN = None
SESSION_ID = None

column_table_general = (
    "event_id",
    "title",
    "post",
    "image",
    "url",
    "price",
    "from_date",
    "to_date",
    "address",
)
dsn_site_database_url = os.environ.get("DSN_SITE_DATABASE_URL")
tables = {
    1: "events_eventsnotapprovednew",
    2: "events_eventsnotapprovedold",
    3: "events_events2post",
    "posting_time": "events_postingtime",
}
DEFAULT_UPDATING_STRFTIME = "00:00"

utc_3 = pytz.timezone("Europe/Moscow")

DEFAULT_UPDATING_STRFTIME = "00:00"
log = get_logger(__file__)


def create_session():
    global CSRFTOKEN
    global SESSION_ID

    login_url = BASE_URL + "login/"
    login_data = dict(
        username=os.environ.get("DSN_USERNAME"),
        password=os.environ.get("DSN_PASSWORD"),
        next=BASE_URL,
    )
    headers = {"User-Agent": UserAgent().random}

    session = requests.session()
    session.get(login_url, headers=headers)

    CSRFTOKEN = session.cookies["csrftoken"]

    login_data["csrfmiddlewaretoken"] = CSRFTOKEN

    response = session.post(login_url, data=login_data, headers=headers)

    SESSION_ID = session.cookies["sessionid"]

    assert response.ok


def _current_session_get(url):
    session = requests.session()

    session.cookies["csrfmiddlewaretoken"] = CSRFTOKEN
    session.cookies["sessionid"] = SESSION_ID

    return session.get(url)


def get_queue(cursor):
    """
    ?
    """
    script = f"SELECT queue FROM {tables[3]} ORDER BY queue DESC LIMIT 1"
    cursor.execute(script)
    return cursor.fetchone()[0] + 2


def get_post_date(cursor):
    """
    ?
    """
    script = f"SELECT post_date FROM {tables[3]} ORDER BY post_date DESC LIMIT 1"
    cursor.execute(script)
    last_post_date = cursor.fetchone()[0]

    return last_post_date + datetime.timedelta(hours=2)  # TODO: BAD!!!!


def check_event_status():
    _current_session_get(url=CHECK_EVENT_STATUS_URL)


def move_approved():
    _current_session_get(url=MOVE_APPROVED_URL)


def remove_old():
    _current_session_get(url=REMOVE_OLD_URL)


def fill_empty_post_time():
    _current_session_get(url=FILL_EMPTY_POST_TIME_URL)


def next_event_to_channel():
    """
    Первое подходящее мероприятие из таблицы 3 для постинга в канал.

    Критерии поиска мероприятия:
    - Поиск происходит от по возрастанию значения `queue`
    - Значение поля `status` равное `ReadyToPost`
    - Наличие значения в поле `post_date` (равное текущему времени)
    """
    events = database.get_all(table="events_events2post")

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
    all_events = database.get_all(table="events_events2post")

    events_to_post = all_events[all_events["post_date"] >= reference]

    if pd.isnull(events_to_post["post_date"]).any():
        log.warn("Some events have not posting datetime.")
        events_to_post = events_to_post[~pd.isnull(events_to_post["post_date"])]

    if len(events_to_post) == 0:
        return None

    return events_to_post.sort_values("queue")["post_date"].iloc[0].to_pydatetime()


def next_updating_time(reference):
    hour, minute = DEFAULT_UPDATING_STRFTIME.split(":")
    update_time = reference.replace(
        hour=int(hour), minute=int(minute)
    ) + datetime.timedelta(days=1)

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
