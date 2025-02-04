from sqlalchemy import func, asc, desc

from .database.models import Events2Posts, Exhibitions, DsnBotEvents, Place
from .database.database_orm import db_session

from datetime import datetime
from typing import List

from .events import Event


def order_maping(model, order_by):
    if model == Place:
        order_mapping = {
            'tt': Place.place_name,
            'mt': Place.place_metro,
            'id': Place.id
        }
        try:
            field, direction = order_by.split('-')
            column = order_mapping.get(field, Place.id)
            sort_order = asc(column) if direction == 'asc' else desc(column)
        except ValueError:
            sort_order = asc(Place.id)
    elif model == Events2Posts:
        order_mapping = {
            'tt': Events2Posts.title,
            'dt': Events2Posts.from_date,
            'pr': Events2Posts.price,
            'ad': Events2Posts.price,
            'id': Events2Posts.id
        }
        try:
            field, direction = order_by.split('-')
            column = order_mapping.get(field, Place.id)
            sort_order = asc(column) if direction == 'asc' else desc(column)
        except ValueError:
            sort_order = asc(Events2Posts.id)
    else:
        sort_order = asc(model.id)

    return sort_order




@db_session
def get_events_by_date_and_category(db, params):
    query = db.query(Events2Posts)\
        .filter((Events2Posts.status == 'Posted') | Events2Posts.is_ready)

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
def get_places(db, params):
    sort_order = order_maping(Place, params.order_by)
    query = db.query(Place).order_by(sort_order)

    if params.ids:
        query = query.filter(Place.id.in_(params.ids))
    else:
        if params.metro:
            query = query.filter(Place.place_metro == params.metro)

        if params.limit:
            query = query.limit(params.limit)
            if params.page:
                query = query.offset(params.page * params.limit)

    places = query.all()
    result = [
        {field: getattr(place, field) for field in (params.fields or place.__table__.columns.keys())}
        for place in places
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
def set_status(db: object, event_id: str, status: str) -> None:
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
def set_post_url(db: object, event_id: str, post_url: str) -> None:
    db.query(Events2Posts).filter_by(event_id=event_id).update({"post_url":post_url})
    db.commit()

@db_session
def get_last_queue_value(db) -> int:
    result = db.query(Events2Posts).filter(status='ReadyToPost').order_by(Events2Posts.queue.desc()).scalar
    return result if result is not None else 0


######## DSN BOT ########
####––––––START––––––####

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

####––––––FINISH––––––####


### Searching functions ###
######–----START----–######


@db_session
def search_events_by_title(db, title: str, limit: int):
    columns = [Events2Posts.id, Events2Posts.title]
    events = db.query(*columns)\
        .filter(Events2Posts.title.ilike(f"%{title}%")).limit(limit).all()
    result = [dict(zip([column.name for column in columns], event)) for event in events]
    return result


@db_session
def search_places_by_name(db, name: str, limit: int):
    columns = Place.id, Place.place_name, Place.place_metro
    places = db.query(*columns)\
        .filter(Place.place_name.ilike(f"%{name}%")).limit(limit).all()
    result = [dict(zip([column.name for column in columns], place)) for place in places]
    return result


####––––––FINISH––––––####