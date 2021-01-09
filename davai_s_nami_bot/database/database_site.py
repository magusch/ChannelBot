import os
from collections import namedtuple

import psycopg2
from psycopg2 import sql

DATABASE_URL_SITE = os.environ.get("DATABASE_URL_SITE")
DB_FOLDER = os.path.dirname(__file__)
SCHEMA_NAME = "schema_site.sql" #TODO: make new scheme
SCHEMA_PATH = os.path.join(DB_FOLDER, SCHEMA_NAME)
TABLE_NAME = "events"

is_table_exists = (
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_name = %s"
)
if DATABASE_URL_SITE is None:
    raise ValueError("Postgresql DATABASE_URL do not found")



def get_db_connection():
    """
    Get database pointer.
    """
    db_conn = psycopg2.connect(DATABASE_URL_SITE)
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