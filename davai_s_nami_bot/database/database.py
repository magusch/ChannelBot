import os

from escraper import EventData4db
import psycopg2

__all__ = ("add2db",)

SQLITE_DB_NAME = "events.database"
DB_FOLDER = os.path.dirname(__file__)
SCHEMA_NAME = "schema.sql"
SCHEMA_PATH = os.path.join(DB_FOLDER, SCHEMA_NAME)
SQLITE_DB_PATH = os.path.join(DB_FOLDER, SQLITE_DB_NAME)
if "DATABASE_URL" in os.environ:
    DATABASE_URL = os.environ["DATABASE_URL"]
else:
    DATABASE_URL = None


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
    if DATABASE_URL is not None:
        db = psycopg2.connect(DATABASE_URL, sslmode="require")
    else:
        db = sqlite3.connect(database=SQLITE_DB_PATH)

    db.row_factory = dict_factory

    # run schema.sql
    with open(SCHEMA_PATH) as file:
        db.executescript(file.read())

    db.commit()

    global db


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
    db.execute(script, data)
    db.commit()


def add2db(events):
    db_columns = EventData4db._fields

    placeholders = ", ".join(["?" for _ in db_columns])
    script = (
        "INSERT INTO events ({}) VALUES ({})"
        .format(", ".join(db_columns), placeholders)
    )

    to_db = [
        [getattr(event, column) for column in db_columns]
        for event in events
    ]

    _insert(script, events)
