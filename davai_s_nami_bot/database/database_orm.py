import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DSN_DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


def db_session(func):
    """Decorator that provides a SQLAlchemy session as the first argument.

    Reentrant: if the caller already has a session (passed as first positional
    arg or as `db` kwarg), reuse it so all calls share one transaction.
    Otherwise, open a new session via get_db_session().
    """
    def wrapper(*args, **kwargs):
        if 'db' in kwargs:
            return func(*args, **kwargs)
        if args and hasattr(args[0], 'query'):
            return func(*args, **kwargs)
        with get_db_session() as db:
            return func(db, *args, **kwargs)
    return wrapper


def orm_to_dict(obj):
    if isinstance(obj, list):
        return [orm_to_dict(item) for item in obj]
    else:        
        return {
            column.name: getattr(obj, column.name)
            for column in obj.__table__.columns
            }