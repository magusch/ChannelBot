import os
from typing import List
from datetime import datetime

import pandas as pd
import psycopg2
from psycopg2 import sql

from ..events import Event


__all__ = ("add", "get_all", "remove", "remove_by_event_id")

TAGS = [
    "event_id",
    "title",
    "post",
    "image",
    "url",
    "price",
    "from_date",
    "to_date",
    "address",
]
DATABASE_URL = os.environ.get("DSN_SITE_DATABASE_URL")
TABLES = [
    "events_eventsnotapprovednew",  # TODO wtf with table names!?
    "events_eventsnotapprovedold",
    "events_events2post",
    "events_postingtime",
    "telegram_posted",  # TODO ещё одна таблица для постов, которые опубликованы в телеграм
]
column_table_add = {
    1: ("explored_date", "approved"),
    3: (
        "explored_date",
        "queue",
        "post_date",
        "status",
    ),
}

if DATABASE_URL is None:
    raise ValueError("Postgresql DATABASE_URL do not found")


def get_db_connection():
    """
    Get database pointer.
    """
    return psycopg2.connect(DATABASE_URL)


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


def get_as_event(table: str, event_id: str) -> Event:
    check_table(table)

    script = sql.SQL("SELECT * FROM {table} WHERE event_id = {event_id}").format(
        table=sql.Identifier(table),
        event_id=sql.Identifier(event_id),
    )
    return Event.from_database(_get(script))


def get_all(table: str) -> pd.DataFrame:
    check_table(table)

    script = sql.SQL("SELECT * FROM {table_name}").format(
        table_name=sql.Identifier(table)
    )

    return _get_dataframe(script)


def check_table(table: str):
    if table not in TABLES:
        raise ValueError(f"Unknown table name: {table}")


def add_events(events: List[Event], table: str) -> None:
    for event in events:
        add(event, table)


def add(event: Event, table: str) -> None:
    check_table(table)

    script = sql.SQL(
        "INSERT INTO {table} ({fields}) values "
        "(%s, %s, %s, %s, %s, cast(%s as TIMESTAMP), cast(%s as TIMESTAMP), %s)"
    ).format(
        table=sql.Identifier(table),
        fields=sql.SQL(", ").join([sql.Identifier(tag) for tag in TAGS]),
    )

    data = [
        event.event_id,
        event.title,
        event.image,
        event.url,
        event.price,
        getattr(event.from_date, "start", None),
        getattr(event.to_date, "start", None),
        event.address,
    ]

    # FIXME
    # - для таблицы 1 и 2 дополнительное поле `Approved` [False]
    # - для таблицы 3 дополнительное поле `Status` [ReadyToPost]

    _insert(script, data)


def remove(date: datetime) -> None:
    script = sql.SQL(
        "DELETE FROM {table} WHERE date_to < cast(%s as TIMESTAMP)"
    ).format(table=sql.Identifier(TABLE_NAME))

    _insert(script, (date,))


def remove_by_event_id(event_id: str) -> None:
    script = sql.SQL("DELETE FROM {table} WHERE id = %s").format(
        table=sql.Identifier(TABLE_NAME),
    )

    _insert(script, (event_id,))


def remove_by_title(title: str) -> None:
    script = sql.SQL("DELETE FROM {table} WHERE title = %s").format(
        table=TABLE_NAME,
    )

    _insert(script, (title,))
