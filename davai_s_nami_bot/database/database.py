import os
from functools import lru_cache

from escraper.parsers import EVENT_TAGS
import psycopg2

__all__ = ("add2db",)

DB_FOLDER = os.path.dirname(__file__)
SCHEMA_NAME = "schema.sql"
SCHEMA_PATH = os.path.join(DB_FOLDER, SCHEMA_NAME)

if "DATABASE_URL" in os.environ:
    DATABASE_URL = os.environ["DATABASE_URL"]
else:
    raise ValueError("Postgresql DATABASE_URL do not found")


def dict_factory(cursor, row):
    """
    Result preprocessing.
    """
    d = {}
    for i, col in enumerate(cursor.description):
        d[col[0]] = row[i]
    return d


def getdb():
    """
    Get database pointer.
    """
    db_conn = psycopg2.connect(DATABASE_URL)
    db_cur = db_conn.cursor()

    db_cur.row_factory = dict_factory

    # run schema.sql
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
    db_cur = getdb().cursor()

    db_cur.execute(script, data)
    # db_cur.close()  # is that need?


def add2db(events):
    db_columns = EVENT_TAGS["to_database"]

    placeholders = ", ".join(["%s" for _ in db_columns])
    script = (
        "INSERT INTO events ({}) VALUES ({})"
        .format(", ".join(db_columns), placeholders)
    )

    for event in events:
        _insert(script, [getattr(event, column) for column in db_columns])
