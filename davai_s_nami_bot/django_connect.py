import os, datetime
import psycopg2

from typing import Any, List
from .events import Event

django_database_url = os.environ.get("DJANGO_DATABASE_URL")
tables = {
    1: 'events_eventsnotapprovednew',
    2: 'events_eventsnotapprovedold',
    3: 'events_events2post',

    'posting_time': 'events_postingtime',
}


column_table_general = ('event_id', 'title', 'post', 'image', 'url', 'price', 'address', 'date_from', 'date_to')
column_table_add = {
        1: ('explored_date', 'approved'),
        3: ('explored_date', 'queue', 'post_date', 'status',),
    }


def get_db_connection():
    """
    Get database pointer.
    """
    db_conn = psycopg2.connect(django_database_url)
    db_cur = db_conn.cursor()

    return db_conn, db_cur


def add_events(
    events: List[Event], explored_date: datetime, table: int = 1
) -> None:

    for event in events:
        add_event(event, explored_date, table)


def add_event(event, explored_date, table=1):
    conn, cursor = get_db_connection()

    values = ""
    for column in column_table_general:
        if type(event[column])==int:
            values += f" {str(event[column])},"
        elif type(event[column])==str:
            values += f" '{event[column]}',"

    values += f" '{explored_date}'::timestamp"
    if table == 1:
        values += ' False, '
    elif table == 3:
        queue = 100 #todo select
        post_date = ''
        status = 'ReadyToPost'
        values += f" {queue}, {post_date}, '{status}',"

    values = values[:-1]

    script = f"INSERT INTO {tables[table]} ({','.join(column_table_general)}, {', '.join(column_table_add[table])} ) VALUES ({values})"

    cursor.execute(script)
    conn.close()

def remove_old_events(table =1, today=datetime.datetime.today()):
    conn, cursor = get_db_connection()

    script = f"DELETE FROM {tables[table]} WHERE date_to<'{today}'::timestamp"

    cursor.execute(script)
    conn.close()


def next_event_to_channel():
    """
    Getting next event_post (str) from table 3 (from up to down).
    """
    tablename = tables[3]

    conn, cursor = get_db_connection()

    script = f"SELECT id, post FROM {tablename} WHERE status='ReadyToPost' ORDER BY queue LIMIT 1"

    cursor.execute(script)

    try:
        id, post = cursor.fetchone()
        script_update = f"UPDATE {tablename} SET status='Posted' WHERE id={id}"
        cursor.execute(script_update)
    except:
        post=None

    conn.close()
    return post


def get_new_events(events):
    existing_ids = list()
    conn, cursor = get_db_connection()
    for table in (1,2,3):
        script = f"SELECT event_id FROM {tables[table]}"
        cursor.execute(script)

        existing_ids += [event_id[0] for event_id in cursor.fetchall()]

    new_events = list()
    for event in events:
        if event.event_id not in existing_ids:
            new_events.append(event)

    return new_events
