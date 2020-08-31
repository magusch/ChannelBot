import os
from collections import namedtuple

import psycopg2


__all__ = (
    "add",
    "remove",
    "event_by_date",
)

TAGS = ["id", "title", "post_id", "date_from", "date_to"]
DB_FOLDER = os.path.dirname(__file__)
SCHEMA_NAME = "schema.sql"
SCHEMA_PATH = os.path.join(DB_FOLDER, SCHEMA_NAME)
DATABASE_URL = os.environ.get("DATABASE_URL")
TABLE_NAME = "dev_events"

is_table_exists = (
    "SELECT table_name FROM information_schema.tables "
    f"WHERE table_name='{TABLE_NAME}'"
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

    data : list of values
        inserting data

    script : str
        executing script
    """
    db_connection = get_db_connection()
    db_cursor = db_connection.cursor()

    db_cursor.execute(script, data)
    db_connection.commit()

    db_connection.close()
    db_cursor.close()


def _get(script):
    db_cursor = get_db_cursor()
    db_cursor.execute(script)

    values = db_cursor.fetchall()

    db_cursor.close()

    return values


def add(event, post_id):
    script = (
        f"INSERT INTO {TABLE_NAME} "
        f"({', '.join(TAGS)}) values "
    )
    placeholder = "(%s, %s, %s, cast(%s as TIMESTAMP))"

    data = [
        event.Event_id,
        event.Title,
        post_id,
        event.From_date.start,
        event.To_date.start,
    ]

    _insert(script + placeholder, data)


def remove(date):
    script = (
        "DELETE FROM {table} WHERE date_from < cast(%s as TIMESTAMP)"
        .format(table=TABLE_NAME)
    )

    _insert(script, [date])


def event_by_date(dt):
    """
    Required for dt (type datetime):
    - hours = 0
    - minutes = 0
    - seconds = 0
    - microseconds = 0

    Only year, month and day.
    """
    script = (
        f"SELECT ({', '.join(TAGS)}) FROM {TABLE_NAME}"
        "WHERE date_from = cast(%s as TIMESTAMP)"
    )

    events = list()
    for values in _get(script):
        events.append(
            dict(title=values[1], post_id=values[2])
        )
    return events
