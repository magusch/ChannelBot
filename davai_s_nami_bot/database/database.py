import os
from collections import namedtuple

import psycopg2
from escraper.parsers import ALL_EVENT_TAGS


__all__ = (
    "add",
    "events_count",
    "get_event_by_id",
    "get_new_events_id",
    "old_events",
    "update_post_id",
    "remove",
)

DB_FOLDER = os.path.dirname(__file__)
SCHEMA_NAME = "schema.sql"
SCHEMA_PATH = os.path.join(DB_FOLDER, SCHEMA_NAME)
DATABASE_URL = os.environ.get("DATABASE_URL")
TABLE_NAME = "timepad_and_radario_events"

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

    db_connection.close()  # is that need?
    db_cursor.close()


def _get(script):
    db_cursor = get_db_cursor()
    db_cursor.execute(script)

    values = db_cursor.fetchall()

    db_cursor.close()

    return values


def get_new_events_id(events):
    db_cursor = get_db_cursor()

    db_cursor.execute(f"SELECT id FROM {TABLE_NAME}")
    database_ids = [i[0] for i in db_cursor.fetchall()]

    db_cursor.close()

    new_events_id = list()

    for event in events:
        if event.id not in database_ids:
            new_events_id.append(event.id)

    return new_events_id


def get_event_by_id(event_id):
    script = (
        "SELECT {columns} FROM {table_name} WHERE id = {id}"
        .format(
            columns=", ".join(ALL_EVENT_TAGS),
            table_name=TABLE_NAME,
            id=event_id,
        )
    )
    values = _get(script)

    if not values:
        raise TypeError(
            f"Event id {event_id} not found in database, because "
            "events in the notion table and in the database does not match"
        )

    return namedtuple("event", ALL_EVENT_TAGS)(
        **{key: val for key, val in zip(ALL_EVENT_TAGS, values[0])}
    )


def add(events):
    # required date as third element ALL_EVENT_TAGS
    script = (
        f"INSERT INTO {TABLE_NAME} "
        f"({', '.join(ALL_EVENT_TAGS)}) values "
    )
    placeholder = (
        "(%s, %s, cast(%s as TIMESTAMP), cast(%s as TIMESTAMP), "
        "%s, %s, %s, %s, %s, %s, %s, %s), "
    )

    data = list()

    for event in events:
        data += [getattr(event, column) for column in ALL_EVENT_TAGS]

    if data:
        _insert(script + (placeholder * len(events))[:-2], data)


def old_events(date):
    db_cursor = get_db_cursor()
    script = f"SELECT id FROM {TABLE_NAME} WHERE date_from < cast(%s as TIMESTAMP)"
    db_cursor.execute(script, [date])

    events_id = [i[0] for i in db_cursor.fetchall()]

    db_cursor.close()

    return events_id


def remove(events_id):
    if events_id:
        script = (
            "DELETE FROM {table_name} WHERE id IN ({ids})"
            .format(
                table_name=TABLE_NAME,
                ids="".join(["%s, " for _ in events_id])[:-2]
            )
        )

        _insert(script, events_id)


def update_post_id(event_id, post_id):
    script = f"UPDATE {TABLE_NAME} SET post_id = %s WHERE id = %s"

    _insert(script, [post_id, event_id])


def events_count():
    script = f"SELECT id FROM {TABLE_NAME}"
    return len(_get(script))
