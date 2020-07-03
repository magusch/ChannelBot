import os
from functools import lru_cache
import warnings

import psycopg2

from ..events import TAGS_TO_DATABASE


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


def getdb():
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


def _get(db, script, names):
    """
    Getting values from `db` by `script`.
    """
    values = db.execute(script, names).fetchall()

    return values


def _insert(script, data):
    """
    Parameters:
    -----------

    data : list of lists
        inserting data

    script : str
        executing script
    """
    db_conn = getdb()
    db_cur = db_conn.cursor()


    db_cur.execute(script, data)
    db_conn.commit()

    db_conn.close()  # is that need?
    db_cur.close()


def add(events):
    # required date as last element TAGS_TO_DATABASE
    script = (
        "INSERT INTO events "
        f"({TAGS_TO_DATABASE}) values "
        "(%s, %s, %s, %s, %s, cast(%s as Date))"
    )

    duplicated_event_ids = list()

    for event in events:
        try:
            _insert(script, [getattr(event, column) for column in TAGS_TO_DATABASE])
        except psycopg2.errors.UniqueViolation:
            warnings.warn(f"Existing event found: '{event.id}', '{event.url}'")
            duplicated_event_ids.append(event.id)

    return duplicated_event_ids


def update(events):
    # FIXME bad: add to database something return
    existing_event_ids = add(events)

    return existing_event_ids


def remove_old_events():
    conn = getdb()

    script = "SELECT id FROM events WHERE date <"
