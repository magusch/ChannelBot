from sqlalchemy import func

from .database.models import Events2Posts, Exhibitions, DsnBotEvents
from .database.database_orm import db_session

from datetime import datetime
from typing import List

from .events import Event


@db_session
def get_events_by_date_and_category(db, params):
    query = db.query(Events2Posts)\
        .filter(Events2Posts.status == 'Posted')

    if params.ids:
        query = query.filter(Events2Posts.id.in_(params.ids))
    else:
        query = query.filter(func.date(Events2Posts.from_date) >= params.date_from.date(),
              func.date(Events2Posts.to_date) <= params.date_to.date()
            )

        if params.category:
           query = query.filter(Events2Posts.main_category_id.in_(params.category))

        query = query.order_by(Events2Posts.from_date.asc())

        if params.limit:
            query = query.limit(params.limit)
            if params.page:
                query = query.offset(params.page * params.limit)

    events = query.all()
    result = [
        {field: getattr(event, field) for field in (params.fields or event.__table__.columns.keys())}
        for event in events
    ]
    return result


@db_session
def get_all_events(db):
    events = db.query(Events2Posts).all()
    result = [
        {column.name: getattr(event, column.name) for column in event.__table__.columns}
        for event in events
    ]
    return result


@db_session
def get_exhibitions(db):
    today = datetime.today()
    exhibitions = db.query(Exhibitions).filter(
        func.date(Exhibitions.date_before) <= today,
    )

    result = [
        {column.name: getattr(exhib, column.name) for column in exhib.__table__.columns}
        for exhib in exhibitions
    ]

    return result


@db_session
def create_event(db, event_data):
    event = Events2Posts(**event_data)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def add_events_to_post(events: List[Event], explored_date: datetime, queue_increase=2):

    value = int(get_last_queue_value())

    def func(value=value, queue_increase=queue_increase):
        while True:
            value += queue_increase
            yield value

    queue_value = func()

    params = dict(status="ReadyToPost")

    list_inserted_ids = []
    for event in events:
        event.update({
            'status': 'ReadyToPost',
            'queue': queue_value,
            'explored_date' : explored_date
        })
        id_list = create_event(event)
        if type(id_list) == list:
            list_inserted_ids.append(id_list[0][0])

    return list_inserted_ids


@db_session
def set_status(db, event_id: str, status: str) -> None:
    """
    Обновить статус записи в таблице Event2Post по идентификатору события.

    Parameters
    ----------
    db : db
        Экземпляр SQLAlchemy сессии.

    event_id : str
        Идентификатор события.

    status : str
        Новый статус для обновления.
    """
    # Проверка существования таблицы не нужна, если используется ORM
    # Найти запись по event_id и обновить статус
    db.query(Events2Posts).filter_by(event_id=event_id).update({"status": status})
    db.commit()



@db_session
def set_post_url(db, event_id: str, post_url: str) -> None:
    db.query(Events2Posts).filter(event_id=event_id).update(post_url=post_url)

@db_session
def get_last_queue_value(db) -> int:
    result = db.query(Events2Posts).filter(status='ReadyToPost').order_by(Events2Posts.queue.desc()).scalar
    return result if result is not None else 0


### DSN BOT ––––––Start–––––– ######

@db_session
def add_posted_event_to_dsn_bot(db, event, post_id):
    event_data = {
        "id": event.event_id, "title": event.title, "post_id": post_id,
        "date_from": event.from_date, "date_to": event.to_date, "price": event.price,
    }

    event = DsnBotEvents(**event_data)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@db_session
def remove_event_from_dsn_bot(db, date):
   db.query(DsnBotEvents).filter(DsnBotEvents.date_to < date).delete(synchronize_session=False)