import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria
from contextlib import contextmanager

from ..city_context import SHARED_CITY, current_city

DATABASE_URL = os.environ.get("DSN_DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# --- Multicity scoping -------------------------------------------------------
# Every ORM SELECT/UPDATE/DELETE that touches a model with __city_scope__ is
# limited to the current city (`city_context`), without each of the ~100 queries
# in crud having to remember it. A forgotten filter would not fail — it would
# quietly show one city's events in another city's channel.
#
# Opt out per statement with `.execution_options(all_cities=True)` where reading
# across cities is the point (taste learns from every city's outcomes; resolving
# the city of a list of ids). Raw `text()` SQL is not covered — filter it by hand.


_scoped_cache = {}


def _city_scoped_mappers():
    """(per-city models, shared models). Recomputed only when a new model is
    mapped — content_generator models register after this module loads."""
    from .models import Base

    mappers = Base.registry.mappers
    cached = _scoped_cache.get(len(mappers))
    if cached is not None:
        return cached
    scoped, shared = [], []
    for mapper in mappers:
        scope = getattr(mapper.class_, '__city_scope__', None)
        if scope == 'city':
            scoped.append(mapper.class_)
        elif scope == 'shared':
            shared.append(mapper.class_)
    _scoped_cache.clear()
    _scoped_cache[len(mappers)] = (scoped, shared)
    return scoped, shared


@event.listens_for(Session, "do_orm_execute")
def _scope_to_current_city(state):
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.execution_options.get("all_cities"):
        return
    # Lazy loads of a relationship / deferred column follow a row that was
    # already scoped when it was loaded.
    if state.is_select and (state.is_column_load or state.is_relationship_load):
        return

    city = current_city()
    scoped, shared = _city_scoped_mappers()
    options = [
        with_loader_criteria(model, model.city_id == city, include_aliases=True)
        for model in scoped
    ] + [
        with_loader_criteria(
            model, model.city_id.in_([city, SHARED_CITY]), include_aliases=True
        )
        for model in shared
    ]
    state.statement = state.statement.options(*options)


def _stamp_city_on_init(target, args, kwargs):
    """Give a new per-city object the city it was created in.

    The column default alone runs at flush time, which can be after the
    `use_city` block that built the object has exited.
    """
    if getattr(type(target), '__city_scope__', None) == 'city' and 'city_id' not in kwargs:
        target.city_id = current_city()


def _install_init_hook():
    from .models import Base

    event.listen(Base, 'init', _stamp_city_on_init, propagate=True)


_install_init_hook()


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