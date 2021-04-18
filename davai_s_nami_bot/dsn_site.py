import os, datetime
import pytz
import psycopg2

from typing import Any, List
from .events import Event

from .logger import catch_exceptions, get_logger


utc_3 = pytz.timezone("Europe/Moscow")

dsn_site_database_url = os.environ.get("DSN_SITE_DATABASE_URL")
tables = {
    1: "events_eventsnotapprovednew",
    2: "events_eventsnotapprovedold",
    3: "events_events2post",
    "posting_time": "events_postingtime",
}
DEFAULT_UPDATING_STRFTIME = "00:00"

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
column_table_add = {
    1: ("explored_date", "approved"),
    3: (
        "explored_date",
        "queue",
        "post_date",
        "status",
    ),
}

log = get_logger(__file__)


def get_db_connection():
    """
    Get database pointer.
    """
    db_conn = psycopg2.connect(dsn_sitedatabase_url)
    db_cur = db_conn.cursor()

    return db_conn, db_cur


def add_events(events: List[Event], explored_date: datetime, table: int = 1) -> None:

    for event in events:
        add_event(event, explored_date, table)


def add_event(event, explored_date, table=1):
    conn, cursor = get_db_connection()
    event = event._asdict()
    values = ""
    for column in column_table_general:
        if type(event[column]) == int:
            values += f" {str(event[column])},"
        elif type(event[column]) == str:
            value = event[column].replace("'", "''")
            values += f" '{value}',"
        elif type(event[column]) == datetime.datetime:
            values += f" '{event[column]}'::timestamp, "
    values += f" '{explored_date}'::timestamp,"
    if table == 1:
        values += " False,"
    elif table == 3:
        queue = get_queue(cursor)
        post_date = get_post_date(cursor)
        status = "ReadyToPost"
        values += f" {queue}, '{post_date}'::timestamp, '{status}',"

    values = values[:-1]

    script = f"INSERT INTO {tables[table]} ({','.join(column_table_general)}, {', '.join(column_table_add[table])} ) VALUES ({values})"
    cursor.execute(script)
    conn.commit()
    conn.close()


def get_queue(cursor):
    script = f"SELECT queue FROM {tables[3]} ORDER BY queue DESC LIMIT 1"
    cursor.execute(script)
    return cursor.fetchone()[0] + 2


def get_post_date(cursor):
    script = f"SELECT post_date FROM {tables[3]} ORDER BY post_date DESC LIMIT 1"
    cursor.execute(script)
    last_post_date = cursor.fetchone()[0]

    return last_post_date + datetime.timedelta(hours=2)  # TODO: BAD!!!!


def move_approved() -> None:
    """
    Moving all approved events (with selected checkbox Approved)
    from table1 and table2 to table3.
    """

    conn, cursor = get_db_connection()

    script = f"SELECT {','.join(column_table_general)}, explored_date FROM {tables[1]} WHERE approved = True"
    cursor.execute(script)
    events = cursor.fetchall()

    script = f"SELECT {','.join(column_table_general)}, explored_date FROM {tables[2]} WHERE approved = True"
    cursor.execute(script)
    events += cursor.fetchall()
    if events:
        event_to_delete = []
        script_insert = f"INSERT INTO {tables[3]} ({','.join(column_table_general)}, {','.join(column_table_add[3])}) VALUES "
        for event in events:
            script_insert += "("
            for i, column in enumerate(column_table_general):
                if column == "event_id":
                    event_to_delete.append(event[i])
                if type(event[i]) == int:
                    script_insert += f" {str(event[i])},"
                elif type(event[i]) == str:
                    script_insert += f" '{event[i]}',"
                elif type(event[i]) == datetime.datetime:
                    script_insert += f" '{event[i]}'::timestamp, "
                else:
                    script_insert += f" {str(event[i])},"
            queue = get_queue(cursor)
            post_date = get_post_date(cursor)
            status = "ReadyToPost"
            script_insert += f"'{event[-1]}'::timestamp, {queue}, '{post_date}'::timestamp, '{status}',"

            script_insert = script_insert[:-1] + "),"

        script_insert = script_insert[:-1]
        cursor.execute(script_insert)

        delete_events = "','".join(event_to_delete)
        script_delete = f"DELETE FROM {tables[1]} WHERE event_id in ('{delete_events}')"
        cursor.execute(script_delete)
        script_delete = f"DELETE FROM {tables[2]} WHERE event_id in ('{delete_events}')"
        cursor.execute(script_delete)
        conn.commit()
    conn.close()


def remove_events(tablename=tables[3], msk_date=datetime.datetime.today()):
    conn, cursor = get_db_connection()

    script = f"DELETE FROM {tablename} WHERE to_date<'{msk_date}'::timestamp"

    cursor.execute(script)
    conn.commit()
    conn.close()


def remove_old_events(msk_date: datetime) -> None:
    for table in (1, 2, 3):
        remove_events(tablename=tables[table], msk_date=msk_date)


def remove_old_events_from_table1(explored_days=7):
    conn, cursor = get_db_connection()

    day = datetime.datetime.today() - datetime.timedelta(days=explored_days)

    script = f"DELETE FROM {tables[1]} WHERE explored_date<'{day}'::timestamp"

    cursor.execute(script)
    conn.commit()
    conn.close()


def next_event_to_channel(columns=column_table_general, counts="1"):
    """
    Getting next event_post (str) from table 3 (from up to down).
    """
    tablename = tables[3]

    conn, cursor = get_db_connection()

    script = f"SELECT {', '.join(columns)} FROM {tablename} WHERE status='ReadyToPost' ORDER BY queue LIMIT {counts}"

    cursor.execute(script)
    events = list()

    db_answer = cursor.fetchall()
    if db_answer:
        for ans in db_answer:
            event = Event.from_dsn_site(ans, columns)
            events.append(event)
            script_update = f"UPDATE {tablename} SET status='Posted' WHERE event_id='{event.event_id}'"
            cursor.execute(script_update)
        conn.commit()

    conn.close()

    if counts == "1":
        return events[0]
    else:
        return events


def get_new_events(events):
    existing_ids = list()
    conn, cursor = get_db_connection()
    for table in (1, 2, 3):
        script = f"SELECT event_id FROM {tables[table]}"
        cursor.execute(script)

        existing_ids += [event_id[0] for event_id in cursor.fetchall()]

    new_events = list()
    for event in events:
        if event.event_id not in existing_ids:
            new_events.append(event)

    return new_events


def not_published_count():
    conn, cursor = get_db_connection()

    script = f"SELECT count(*) FROM {tables[3]} WHERE status!='Posted'  "

    cursor.execute(script)
    count = cursor.fetchone()[0]
    cursor.close()

    return count


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
    columns = columns_for_posting_time
    posting_time = None
    reference = reference.replace(tzinfo=utc_3)
    conn, cursor = get_db_connection()
    script = f"SELECT {', '.join(columns)} FROM {tables[3]} WHERE status!='Posted' ORDER BY post_date"

    cursor.execute(script)
    events = cursor.fetchall()

    for event in events:
        title = event[columns.index("title")]
        posting_time = event[columns.index("post_date")]

        if posting_time is None:
            log.warn(
                "Unexcepteble warning: event in table 3 have not "
                f"posting datetime. Event title: {title}."
            )
            # to next valid event
            continue
        if posting_time < reference:
            log.warn(
                "Warning: event in table 3 have posting datetime in the past.\n"
                f"Event title: {title}."
            )
            # skip for events that posting time in past
            if reference.hour in range(7, 18):
                posting_time = reference + datetime.timedelta(hours=1)
        break

    return posting_time


def next_updating_time(reference):
    reference = reference.replace(tzinfo=utc_3)
    everyday_str = DEFAULT_UPDATING_STRFTIME
    everyday_list = everyday_str.split(":")
    hour, minute = everyday_list
    update_time = reference.replace(
        hour=int(hour), minute=int(minute)
    ) + datetime.timedelta(days=1)

    return update_time


def next_task_time(msk_today):
    task_time = None
    msk_today = msk_today.replace(tzinfo=utc_3)
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
