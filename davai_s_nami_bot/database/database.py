import os

import pandas as pd
import psycopg2
from psycopg2 import sql

__all__ = ("add", "get_all", "remove", "remove_by_event_id")

TAGS = ["id", "title", "post_id", "date_from", "date_to", "price"]
DB_FOLDER = os.path.dirname(__file__)
SCHEMA_NAME = "schema.sql"
SCHEMA_PATH = os.path.join(DB_FOLDER, SCHEMA_NAME)
DATABASE_URL = os.environ.get("DATABASE_URL")
TABLE_NAME = "dev_events"

is_table_exists = (
    "SELECT table_name FROM information_schema.tables WHERE table_name = %s"
)
if DATABASE_URL is None:
    raise ValueError("Postgresql DATABASE_URL do not found")


def get_db_connection():
    """
    Get database pointer.
    """
    db_conn = psycopg2.connect(DATABASE_URL)
    db_cur = db_conn.cursor()

    db_cur.execute(is_table_exists, (TABLE_NAME,))
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


def _get_dataframe(script):
    db_connection = get_db_connection()

    return pd.read_sql_query(script, con=db_connection)


def get_all():
    script = sql.SQL("SELECT * FROM {table_name}").format(
        table_name=sql.Identifier(TABLE_NAME)
    )

    return _get_dataframe(script)


def add(event, post_id):
    script = sql.SQL(
        "INSERT INTO {table} ({fields}) values "
        "(%s, %s, %s, cast(%s as TIMESTAMP), cast(%s as TIMESTAMP), %s)"
    ).format(
        table=sql.Identifier(TABLE_NAME),
        fields=sql.SQL(", ").join([sql.Identifier(tag) for tag in TAGS]),
    )

    data = [
        event.Event_id,
        event.Title,
        post_id,
        None if event.From_date is None else event.From_date.start,
        None if event.To_date is None else event.To_date.start,
        None if event.Price is None else event.Price,
    ]

    _insert(script, data)


def remove(date):
    script = sql.SQL("DELETE FROM {table} WHERE date_to < cast(%s as TIMESTAMP)").format(
        table=sql.Identifier(TABLE_NAME)
    )

    _insert(script, (date,))


def remove_by_event_id(event_id):
    script = sql.SQL("DELETE FROM {table} WHERE id = %s").format(
        table=sql.Identifier(TABLE_NAME),
    )

    _insert(script, (event_id,))


def remove_by_title(title):
    script = sql.SQL("DELETE FROM {table} WHERE title = %s").format(
        table=TABLE_NAME,
    )

    _insert(script, (title,))
