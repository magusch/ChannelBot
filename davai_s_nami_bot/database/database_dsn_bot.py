import os
import psycopg2
from psycopg2 import sql

from ..events import Event

DSN_DATABASE_URL = os.environ.get("DSN_DATABASE_URL")

DSN_BOT_TABLE = "bot_events"   #table for telegram bot "Давай с нами, Бот"
DSN_BOT_TAGS = ["id", "title", "post_id", "date_from", "date_to", "price"] # Tags for telegram bot "Давай с нами, Бот"


def get_db_connection():
    """
    Get database pointer.
    """
    return psycopg2.connect(DSN_DATABASE_URL)


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


def add_event_for_dsn_bot(event, post_id):
    script = sql.SQL(
        "INSERT INTO {table} ({fields}) values "
        "(%s, %s, %s, cast(%s as TIMESTAMP), cast(%s as TIMESTAMP), %s)"
    ).format(
        table=sql.Identifier(DSN_BOT_TABLE),
        fields=sql.SQL(", ").join([sql.Identifier(tag) for tag in DSN_BOT_TAGS]),
    )

    data = [
        event.event_id,
        event.title,
        post_id,
        event.from_date,
        event.to_date,
        event.price,
    ]

    _insert(script, data)


def remove_event_from_dsn_bot(date):
    script = sql.SQL("DELETE FROM {table} WHERE date_to < cast(%s as TIMESTAMP)").format(
        table=sql.Identifier(DSN_BOT_TABLE)
    )
    _insert(script, (date,))


def select_dsn_bot():
    script = "SELECT * FROM bot_events Limit 10"
    _get(script)