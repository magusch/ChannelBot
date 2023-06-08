import os
from typing import List
from datetime import datetime

import pytz
import pandas as pd
import psycopg2
from psycopg2 import sql

from ..events import Event


__all__ = (
    "add",
    "add_events",
    "get_all",
    "get_ready_to_post",
    "get_scrape_it_events",
    "get_from_all_tables",
    "remove",
    "remove_by_event_id",
    "set_status",
)

TAGS = [
    "event_id",
    "title",
    "post",
    "image",
    "url",
    "price",
    "address",
    "from_date",
    "to_date",
    "explored_date",
]
DATABASE_URL = os.environ.get("DATABASE_URL")
TIMEZONE = pytz.timezone("Europe/Moscow")
TABLES = [
    "events_eventsnotapprovednew",  # TODO wtf with table names!?
    "events_eventsnotapprovedold",
    "events_events2post",
    "events_postingtime",
    "dev_events",  # telegram_posted TODO ещё одна таблица для постов, которые опубликованы в телеграм
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


def _convert_to_timezone(values):
    if isinstance(values, list):
        raise TypeError("TODO")

    elif isinstance(values, pd.DataFrame):
        datetime_columns = values.columns[
            [isinstance(i, pd.DatetimeTZDtype) for i in values.dtypes]
        ]
        values[datetime_columns] = values[datetime_columns].apply(
            lambda x: x.dt.tz_convert("Europe/Moscow")
        )

    else:
        raise TypeError(f"Unknown type: {type(values).__name__}")

    return values


def _get(script):
    db_cursor = get_db_cursor()
    db_cursor.execute(script)

    values = db_cursor.fetchall()

    db_cursor.close()

    return _convert_to_timezone(values)



def _get_dataframe(script):
    db_connection = get_db_connection()

    return _convert_to_timezone(pd.read_sql_query(script, con=db_connection))


def get_as_event(table: str, event_id: str) -> Event:
    # TODO проверить работоспособность
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


def get_ready_to_post(table: str) -> pd.DataFrame:
    check_table(table)

    script = sql.SQL("SELECT * FROM {table_name} WHERE status='ReadyToPost'").format(
        table_name=sql.Identifier(table)
    )

    return _get_dataframe(script)


def get_scrape_it_events(table: str) -> pd.DataFrame:
    check_table(table)

    script = sql.SQL("SELECT event_id, url FROM {table_name} WHERE status='Scrape'").format(
        table_name=sql.Identifier(table)
    )

    return _get_dataframe(script)


def get_from_all_tables() -> pd.DataFrame:
    return pd.concat(
        [
            get_all(table="events_eventsnotapprovednew"),
            get_all(table="events_eventsnotapprovedold"),
            get_all(table="events_events2post"),
        ],
        sort=False,
    )


def rows_number(table: str) -> int:
    check_table(table)

    script = sql.SQL("SELECT count(*) FROM {table}").format(table=sql.Identifier(table))
    count = _get_dataframe(script)

    return count.loc[0, "count"]


def check_table(table: str):
    if table not in TABLES:
        raise ValueError(f"Unknown table name: {table}")


def get_last_queue_value(table: str) -> int:
    script = sql.SQL(
        "SELECT queue FROM {table} WHERE status = 'ReadyToPost' ORDER BY queue DESC LIMIT 1"
    ).format(
        table=sql.Identifier(table),
    )

    queue = _get_dataframe(script)

    if queue.empty:
        return 0

    return queue.loc[0, "queue"]


def add_events(
    events: List[Event],
    explored_date: datetime,
    table: str = "events_eventsnotapprovednew",
    queue_increase=2,
) -> None:
    queue_value = None

    if table == "events_events2post":
        value = int(get_last_queue_value(table))

        def func(value=value, queue_increase=queue_increase):
            while True:
                value += queue_increase
                yield value

        queue_value = func()

        params = dict(status="ReadyToPost")

    else:
        queue_value = None
        params = dict(approved=False)

    for event in events:
        add(event, table, explored_date, queue_value, constant_params=params)


def add(
    event: Event,
    table: str,
    explored_date: datetime,
    queue_value: int = None,
    constant_params: dict = None,
) -> None:
    check_table(table)

    data = [
        event.event_id,
        event.title,
        event.post,
        event.image or "",
        event.url,
        event.price,
        event.address,
        event.from_date,
        event.to_date,
        explored_date,
    ]

    tags = TAGS[:]
    if queue_value:
        tags.insert(0, "queue")
        data.insert(0, next(queue_value))

    if constant_params:
        for tag, value in constant_params.items():
            tags.insert(0, tag)
            data.insert(0, value)

    script = sql.SQL(
        "INSERT INTO {table} ({fields}) values "
        "({placeholders}, "
        "cast(%s as TIMESTAMP), cast(%s as TIMESTAMP), cast(%s as TIMESTAMP))"
    ).format(
        table=sql.Identifier(table),
        fields=sql.SQL(", ").join([sql.Identifier(tag) for tag in tags]),
        placeholders=sql.SQL(", ").join([sql.SQL("%s") for tag in tags[:-3]]),
    )

    # FIXME
    # - для таблицы 1 и 2 дополнительное поле `approved` [default `False`]
    # - для таблицы 1 и 2 дополнительное поле `explored_date`
    # - для таблицы 3 дополнительное поле `status` [default `ReadyToPost`]
    # - для таблицы 3 дополнительное поле `queue`

    _insert(script, data)


def remove_by_event_id(
    event_ids: List[str],
    table: str = "events_events2post",
) -> None:

    script = sql.SQL("DELETE FROM {table} WHERE event_id in (%s)").format(
        table=sql.Identifier(table),
    )
    string_events_ids = "'" + "', '".join(event_ids) + "'"
    _insert(script, (string_events_ids,))


def remove(date: datetime) -> None:
    script = sql.SQL(
        "DELETE FROM {table} WHERE date_to < cast(%s as TIMESTAMP)"
    ).format(table=sql.Identifier(TABLE_NAME))

    _insert(script, (date,))


def remove_by_title(title: str) -> None:
    script = sql.SQL("DELETE FROM {table} WHERE title = %s").format(
        table=sql.Identifier(TABLE_NAME),
    )

    _insert(script, (title,))


def set_status(table: str, event_id: str, status: str) -> None:
    check_table(table)

    script = sql.SQL("UPDATE {table} SET status = %s WHERE event_id = %s").format(
        table=sql.Identifier(table)
    )

    _insert(script, data=(status, event_id))
