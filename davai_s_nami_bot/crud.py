from sqlalchemy import func, asc, desc, exc, or_
from sqlalchemy.orm import joinedload

from .database.models import Events2Posts, EventsNotApproved, Exhibitions, DsnBotEvents, Place, ApiRequestLog,\
    DsnBotUserEvents, DsnUser
from .database.database_orm import db_session

from .pydantic_models import UserCreate
from .core.security import get_password_hash

from datetime import datetime, timedelta, timezone
from typing import List

from .events import Event


MODEL_REGISTRY = {
    "events_events2post": Events2Posts,
    "events_eventsnotapprovednew": EventsNotApproved,
    #"events_eventsnotapprovedproposed": EventsNotApprovedProposed,
    "events_event": Event,
    'exhibitions': Exhibitions,
}


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
    query = db.query(Events2Posts).options(joinedload(Events2Posts.place))

    if params.status != 'all':
        query = query.filter((Events2Posts.status == 'Posted') | Events2Posts.is_ready)

    dict_requests = {}
    if params.ids:
        query = query.filter(Events2Posts.id.in_(params.ids))
        dict_requests['ids'] = params.ids
    else:
        query = query.filter(func.date(Events2Posts.to_date) >= params.date_from.date())
        dict_requests['date_from'] = params.date_from

        if params.date_to:
            query = query.filter(func.date(Events2Posts.from_date) <= params.date_to.date())
            dict_requests['date_to'] = params.date_to

        if params.category:
            positive_categories = [c for c in params.category if c > 0]
            negative_categories = [abs(c) for c in params.category if c < 0]

            if positive_categories:
                query = query.filter(Events2Posts.main_category_id.in_(positive_categories))
            elif negative_categories:
                query = query.filter(~Events2Posts.main_category_id.in_(negative_categories))

            dict_requests['category'] = params.category

        if params.place:
            positive_places = [c for c in params.place if c > 0]
            negative_places = [abs(c) for c in params.place if c < 0]

            if positive_places:
                query = query.filter(Events2Posts.place_id.in_(positive_places))
            elif negative_places:
                query = query.filter(~Events2Posts.place_id.in_(negative_places))

            dict_requests['place'] = params.place

        query = query.order_by(Events2Posts.from_date.asc())

    total_count = query.count()
    if params.limit:
        query = query.limit(params.limit)
        dict_requests['limit'] = params.limit
        if params.page:
            query = query.offset(params.page * params.limit)
            dict_requests['page'] = params.page

    events = query.all()

    event_dict_list = []

    for event in events:
        event_data = {
            field: getattr(event, field)
            for field in (params.fields or event.__table__.columns.keys())
        }

        if event.place:
            event_data['address'] = f"{event.place.place_name}, {event.place.place_address}, м.{event.place.place_metro}"
            event_data["place"] = {
                "id": event.place.id, "place_name": event.place.place_name,
                "place_address": event.place.place_address,
                "place_metro": event.place.place_metro
            }

        event_dict_list.append(event_data)

    if params.fields:
        dict_requests['fields'] = params.fields

    return {'events': event_dict_list, 'total_count': total_count, 'request': dict_requests}


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
def get_events_from_all_tables(db):
    """
    Get all events from all tables

    Returns:
        List of Event objects
    """
    tables = [Events2Posts, EventsNotApproved]
    events = []

    for table in tables:
        rows = db.query(table).all()
        events.extend([Event.from_database(event) for event in rows])

    return events


@db_session
def get_approved_events(db, params):
    query = db.query(Events2Posts)

    if params.ids:
        query = query.filter(Events2Posts.id.in_(params.ids))
    else:
        if params.date_from:
            query = query.filter(func.date(Events2Posts.from_date) <= params.date_from.date())
        if params.date_to:
            query = query.filter(func.date(Events2Posts.to_date) <= params.date_to.date())

        if params.limit:
            query = query.limit(params.limit)
            if params.page:
                query = query.offset(params.page * params.limit)

    events = query.all()

    event_dict_list = []

    for event in events:
        event_data = {
            field: getattr(event, field)
            for field in (params.fields or event.__table__.columns.keys())
        }

        if event.place:
            event_data['address'] = f"{event.place.place_name}, {event.place.place_address}, м.{event.place.place_metro}"
            event_data["place"] = {
                "id": event.place.id,
                "place_name": event.place.place_name,
                "place_address": event.place.place_address,
                "place_metro": event.place.place_metro
            }

        event_dict_list.append(event_data)

    return event_dict_list


@db_session
def get_event_id_by_prefix(db, site_prefix):
    """
    Get event ID by site name

    Args:
        site_prefix (str): The site prefix to search for event_id

    Returns:
        List[str] or None: The event ID if found, otherwise None
    """

    events_not_approved = db.query(EventsNotApproved).filter(EventsNotApproved.event_id.like(f'{site_prefix}-%')).all()
    event_ids = [event.event_id for event in events_not_approved]
    events_to_post = db.query(Events2Posts).filter(Events2Posts.event_id.like(f'{site_prefix}-%')).all()
    event_ids.extend([event.event_id for event in events_to_post])
    return event_ids


@db_session
def get_ready_to_post_events(db):
    """
    Get all events with 'ReadyToPost' status

    Returns:
        List of events with ReadyToPost status
    """
    events = db.query(Events2Posts).filter(Events2Posts.status == 'ReadyToPost').all()

    # Преобразуем объекты SQLAlchemy в объекты Event
    result = [Event.from_database(event) for event in events]

    return result


@db_session
def get_event_to_post_now(db):
    """
    Get events that are ready to post and scheduled within 5 minutes of current time

    Returns:
        List of events ready to post now
    """
    now = datetime.utcnow()
    events = db.query(Events2Posts).filter(
        Events2Posts.status == 'ReadyToPost',
        Events2Posts.post_date.between(
            now - timedelta(minutes=5),
            now + timedelta(minutes=5)
        )
    ).order_by(Events2Posts.queue).all()

    if not events:
        return None

    # Преобразуем объекты SQLAlchemy в объекты Event
    result = [Event.from_database(event) for event in events]

    return result


@db_session
def get_scrape_it_events(db) -> List[Event]:
    events = db.query(Events2Posts).filter(Events2Posts.status == 'Scrape').all()
    events = [Event.from_database(event) for event in events]

    return events


@db_session
def delete_events2post_by_event_id(db, event_ids: list[str]):
    db.query(Events2Posts).filter(Events2Posts.event_id.in_(event_ids)).delete(synchronize_session=False)


@db_session
def update_approved_event(db, event_id: int, new_event_data: dict):
    try:
        event = db.query(Events2Posts).filter(Events2Posts.id == event_id).one()
        for key, value in new_event_data.items():
            if hasattr(event, key) and 'date' not in key:
                setattr(event, key, value)
        return True
    except exc.NoResultFound:
        return None


@db_session
def get_not_approved_events(db, params):
    query = db.query(EventsNotApproved)

    if params.ids:
        query = query.filter(EventsNotApproved.id.in_(params.ids))
    else:
        if params.date_from:
            query = query.filter(func.date(EventsNotApproved.explored_date) <= params.date_from.date())
        if params.date_to:
            query = query.filter(func.date(EventsNotApproved.explored_date) <= params.date_to.date())

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
def update_not_approved_events_set_approved(db, event_ids=[]):
    db.query(EventsNotApproved)\
        .filter(EventsNotApproved.id.in_(event_ids))\
        .update({'approved': 1})


@db_session
def update_expired_events(db, date):
    db.query(Events2Posts) \
        .filter(Events2Posts.to_date < date, Events2Posts.is_ready == False) \
        .filter(or_(Events2Posts.post_url.is_(None), Events2Posts.post_url == '')) \
        .delete(synchronize_session=False)
    db.query(Events2Posts)\
        .filter(Events2Posts.to_date < date, Events2Posts.status == 'ReadyToPost', Events2Posts.is_ready == True)\
        .update({'status': 'Posted', 'post_date': None})
    db.query(Events2Posts) \
        .filter(Events2Posts.status == 'Spam') \
        .delete(synchronize_session=False)


@db_session
def remove_old_not_approved_events(db, date):
    db.query(EventsNotApproved) \
        .filter(EventsNotApproved.to_date < date) \
        .delete(synchronize_session=False)


@db_session
def get_exhibitions(db):
    today = datetime.today()
    exhibitions = db.query(Exhibitions).filter(
        func.date(Exhibitions.date_before) >= today,
    )

    result = [
        {column.name: getattr(exhib, column.name) for column in exhib.__table__.columns}
        for exhib in exhibitions
    ]

    return result


@db_session
def create_event(db, event_data: dict, model):
    """
    Make new row in DB.

    Parameters
    ----------
    db : db
        DB session of SQLAlchemy .

    event_data : dict
        data for making row.

    model : class
        model SQLAlchemy.

    Returns
    -------
    object
        Maked object SQLAlchemy.
    """
    event = model(**event_data)
    db.add(event)
    db.commit()
    db.refresh(event)
    return {"id": event.id} # or make Event model


def add_events_to_post(events: List[Event], explored_date: datetime, queue_increase=2):
    """
    Make new rows in table Events2Posts for posting.

    Parameters
    ----------
    events : List[Event]
        List of events for adding.

    explored_date : datetime
        Date of exploration.

    queue_increase : int
        Step of queue increase.

    Returns
    -------
    List[int]
        List of added events IDs.
    """
    value = int(get_last_queue_value())

    def func(value=value, queue_increase=queue_increase):
        while True:
            value += queue_increase
            yield value

    queue_value_gen = func()

    list_inserted_ids = []
    for event in events:

        event_dict = event.to_dict()
        event_dict.update({
            'status': 'ReadyToPost',
            'queue': next(queue_value_gen),
            'explored_date': explored_date
        })

        new_event = create_event(event_dict, Events2Posts)
        if new_event and 'id' in new_event:
            list_inserted_ids.append(new_event['id'])

    return list_inserted_ids


def add_events(events: List[Event], explored_date: datetime, table: str = "events_eventsnotapprovednew"):
    """
    Add events to specified table.

    Parameters
    ----------
    events : List[Event]
        List of events for adding.

    explored_date : datetime
        Date of exploration.

    table : str
        Name of table for adding.

    Returns
    -------
    List[int]
        List of added events IDs.
    """
    model = MODEL_REGISTRY.get(table)
    if not model:
        raise ValueError(f"Неизвестная таблица: {table}")

    list_inserted_ids = []
    for event in events:
        # Преобразуем Event в словарь
        event_dict = event.to_dict()

        # Добавляем дополнительные поля
        event_dict.update({
            'approved': False,
            'explored_date': explored_date,
        })

        # Создаем новую запись в базе данных
        new_event = create_event(event_dict, model)
        if new_event and 'id' in new_event:
            list_inserted_ids.append(new_event['id'])

    return list_inserted_ids


@db_session
def set_status(db: object, event_id: str, status: str) -> None:
    """
    Update status of row in table Event2Post by event ID.

    Parameters
    ----------
    db : db
        DB session of SQLAlchemy.

    event_id : str
        Event ID.

    status : str
        New status for updating.
    """
    event = db.query(Events2Posts).filter_by(event_id=event_id).first()
    if event:
        event.status = status


@db_session
def set_post_url(db: object, event_id: str, post_url: str) -> None:
    db.query(Events2Posts).filter_by(event_id=event_id).update({"post_url": post_url})


@db_session
def get_last_queue_value(db) -> int:
    result = db.query(Events2Posts.queue).filter_by(status='ReadyToPost').order_by(Events2Posts.queue.desc()).first()
    last_queue_value = result[0] if result and result[0] is not None else 0
    return last_queue_value


@db_session
def save_api_request_log(db, request_info: dict):
    api_request_log = ApiRequestLog(**request_info)
    db.add(api_request_log)


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
def add_exhibition_to_dsn_bot(db, event, post_id):
    event_data = {
        "title": event.title, "post_id": post_id, "date_before": event.to_date, "price": event.price,
    }
    db.add(Exhibitions(**event_data))


@db_session
def remove_event_from_dsn_bot(db, date):
    db.query(DsnBotEvents).filter(DsnBotEvents.date_to < date).delete(synchronize_session=False)


@db_session
def event_reminder(db):
    now = datetime.now()

    future_reminds = (
        db.query(DsnBotUserEvents).options(
            joinedload(DsnBotUserEvents.user), joinedload(DsnBotUserEvents.event)
                                           ).filter(
            DsnBotUserEvents.is_remind == True, DsnBotUserEvents.remind_datetime > now
        ).all()
    )

    result = []
    for event in future_reminds:
        result.append({
            'telegram_id': event.user.telegram_id if event.user else None,
            'post_url': event.event.post_url if event.event else None,
            'title': event.event.title if event.event else None,
            'price': event.event.price if event.event else None,
            'remind_datetime': event.remind_datetime
        })
    return result


@db_session
def get_pending_reminders(db):
    now = datetime.now(timezone.utc)

    query = (
        db.query(DsnBotUserEvents)
            .options(
            joinedload(DsnBotUserEvents.user),
            joinedload(DsnBotUserEvents.event)
        )
            .filter(
            DsnBotUserEvents.remind_datetime != None,
            DsnBotUserEvents.remind_datetime <= now,
            DsnBotUserEvents.remind_datetime >= now - timedelta(minutes=60),
            DsnBotUserEvents.remind_sent == False,
            # DsnBotUserEvents.remind_attempts < max_attempts,
        )
    )

    reminders = []
    for remind_event in query.all():
        reminders.append({
            'id':              remind_event.id,
            'telegram_id':     remind_event.user.telegram_id if remind_event.user else None,
            'post_url':        remind_event.event.post_url if remind_event.event else None,
            'title':           remind_event.event.title if remind_event.event else None,
            'price':           remind_event.event.price if remind_event.event else None,
            'remind_datetime': remind_event.remind_datetime,
        })

    return reminders


@db_session
def mark_reminder_sent(db, event_id: int):
    remind_event = db.query(DsnBotUserEvents).get(event_id)
    if remind_event:
        remind_event.remind_sent = True
        db.commit()


####––––––FINISH––––––####


### Searching functions ###
######–----START----–######


@db_session
def search_events_by_string(db, string: str, limit: int):
    columns = [Events2Posts.id, Events2Posts.title, Events2Posts.place_id, Events2Posts.image,
               Events2Posts.main_category_id, Events2Posts.from_date, Events2Posts.to_date]
    events = db.query(*columns)\
        .filter((Events2Posts.title.ilike(f"%{string}%")) | (Events2Posts.category.ilike(f"%{string}%")))\
        .limit(limit).all()
    return [dict(zip([column.name for column in columns], event)) for event in events]


@db_session
def search_places_by_name(db, name: str, limit: int):
    columns = Place.id, Place.place_name, Place.place_metro
    places = db.query(*columns)\
        .filter(Place.place_name.ilike(f"%{name}%")).limit(limit).all()
    result = [dict(zip([column.name for column in columns], place)) for place in places]
    return result

####––––––FINISH––––––####

### USER AUTH function ###
######–----START----–######
@db_session
def register_user(db, user_data: UserCreate):
    db_user = db.query(DsnUser).filter(DsnUser.email == user_data.email).first()
    if db_user:
        return None  # User already exists

    hashed_password = get_password_hash(user_data.password)

    new_user = DsnUser(
        email=user_data.email,
        hashed_password=hashed_password,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        telegram_nickname=user_data.telegram_nickname,
        is_active=True
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    new_user_dict = new_user.__dict__
    return new_user_dict

####––––––FINISH––––––######