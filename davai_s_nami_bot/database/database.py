import os
from collections import namedtuple
from functools import lru_cache
import warnings

import psycopg2
from escraper.parsers import ALL_EVENT_TAGS


__all__ = ("add", "update")

DB_FOLDER = os.path.dirname(__file__)
SCHEMA_NAME = "schema.sql"
SCHEMA_PATH = os.path.join(DB_FOLDER, SCHEMA_NAME)
DATABASE_URL = os.environ.get("DATABASE_URL")

is_table_exists = (
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_name='events'"
)
if DATABASE_URL is None:
    raise ValueError("Postgresql DATABASE_URL do not found")


def get_db_connection():
    """
    Get database pointer.
    """
    db_conn = psycopg2.connect(DATABASE_URL)
    db_cur = db_conn.cursor()

    db_cur.execute(is_table_exists)
    if not db_cur.fetchall():
        with open(SCHEMA_PATH) as file:
            db_cur.execute(file.read())

        db_conn.commit()

    db_cur.close()

    return db_conn


def get_db_cursor():
    return get_db_connection().cursor()


def _insert(script, data):
    """
    Parameters:
    -----------

    data : list of lists
        inserting data

    script : str
        executing script
    """
    db_connection = get_db_connection()
    db_cursor = db_connection.cursor()

    db_cursor.execute(script, data)
    db_connection.commit()

    db_connection.close()  # is that need?
    db_cursor.close()


def _get(script):
    db_cursor = get_db_cursor()
    db_cursor.execute(script)

    return db_cursor.fetchall()


def get_existing_events_id(events):
    db_cursor = get_db_cursor()

    db_cursor.execute("SELECT id FROM events")
    database_ids = [i[0] for i in db_cursor.fetchall()]

    existing_events_id = list()

    for event in events:
        if event.id in database_ids:
            existing_events_id.append(event.id)

    return existing_events_id


def get_event_by_id(event_id):
    script = (
        "SELECT {columns} FROM events WHERE id = {id}"
        .format(
            columns=", ".join(ALL_EVENT_TAGS),
            id=event_id,
        )
    )
    values = _get(script)[0]

    return namedtuple("event", ALL_EVENT_TAGS)(
        **{key: val for key, val in zip(ALL_EVENT_TAGS, values)}
    )


def add(events):
    # required date as third element ALL_EVENT_TAGS
    script = (
        "INSERT INTO events "
        f"({', '.join(ALL_EVENT_TAGS)}) values "
        "(%s, %s, cast(%s as TIMESTAMP), %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )

    for event in events:
        _insert(script, [getattr(event, column) for column in ALL_EVENT_TAGS])


def remove_old_events(date):
    script = "DELETE FROM events WHERE date_from < cast(%s as TIMESTAMP)"

    _insert(script, [date])


def update_post_id(event_id, post_id):
    script = "UPDATE events SET post_id = %s WHERE id = %s"
        
    _insert(script, [post_id, event_id])
