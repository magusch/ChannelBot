import random

from sqlalchemy import func, asc, desc, exc, or_, and_
from sqlalchemy.orm import joinedload

from .database.models import Events2Posts, EventsNotApproved, Exhibitions, DsnBotEvents, Place, PlaceKeyword, \
    ApiRequestLog, DsnBotUserEvents, DsnUser, DsnUserEvent, Category, SubCategory
from .database.database_orm import db_session

from .pydantic_models import UserCreate, UserUpdate
from .core.security import get_password_hash, verify_password

from datetime import datetime, timedelta, timezone
from typing import List

from .events import Event
from .scoring import calculate_score, resolve_category_id
from .adaptive_scoring import merge_adaptive_config, load_from_redis
from .settings.settings_loader import settings


MODEL_REGISTRY = {
    "events_events2post": Events2Posts,
    "events_eventsnotapprovednew": EventsNotApproved,
    #"events_eventsnotapprovedproposed": EventsNotApprovedProposed,
    "events_event": Event,
    'exhibitions': Exhibitions,
}

# Heavy / non-JSON-serializable columns excluded from default API responses.
# pgvector returns numpy.ndarray which json.dumps cannot encode.
_EVENT_EXCLUDED_DEFAULT_FIELDS = {
    'embedding', 'embedding_model', 'embedding_updated_at',
}


def _default_event_fields(model):
    return [
        c for c in model.__table__.columns.keys()
        if c not in _EVENT_EXCLUDED_DEFAULT_FIELDS
    ]


def order_maping(model, order_by):
    if model == Place:
        order_mapping = {
            'title': Place.place_name,
            'metro': Place.place_metro,
            'id': Place.id
        }
        try:
            field, direction = order_by.split('-')
            column = order_mapping.get(field, model.id)
            sort_order = asc(column) if direction == 'asc' else desc(column)
        except ValueError:
            sort_order = asc(model.id)
    elif model == Events2Posts:
        order_mapping = {
            'title': Events2Posts.title,
            'date': Events2Posts.to_date,
            'price': Events2Posts.price_int,
            'ad': Events2Posts.price,
            'id': Events2Posts.id
        }

        try:
            field, direction = order_by.split('-')
            column = order_mapping.get(field, model.to_date)
            sort_order = asc(column) if direction == 'asc' else desc(column)
        except ValueError:
            sort_order = asc(model.id)
    else:
        sort_order = asc(model.id)

    return sort_order


@db_session
def get_events_by_date_and_category(db, params):
    sort_order = order_maping(Events2Posts, params.order_by)
    query = db.query(Events2Posts).options(joinedload(Events2Posts.place)).order_by(sort_order)

    if params.status != 'all':
        query = query.filter(
            Events2Posts.status.in_(('Posted', 'OnlyApi'))
            | (
                (Events2Posts.status == 'ReadyToPost')
                & Events2Posts.is_ready
            )
        )

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

        if params.price_max:
            query = query.filter(Events2Posts.price_int <= params.price_max)
            dict_requests['price_max'] = params.price_max

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
            for field in (params.fields or _default_event_fields(Events2Posts))
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
            for field in (params.fields or _default_event_fields(Events2Posts))
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
def get_unprepared_events(
    db,
    limit: int = 15,
    queue_head: int | None = None,
    nearest_count: int | None = None,
    nearest_pool_size: int | None = None,
    top_score_count: int | None = None,
):
    """Select unprepared events (status=ReadyToPost, is_ready IS NULL) in 3 tiers:

    1. Queue head — events with lowest ``queue`` (next to be posted; catches up
       missed AI-prep so they're ready when their turn comes).
    2. Nearest by date — random sample from the ``nearest_pool_size`` upcoming
       events ordered by ``from_date``.
    3. Top score — fill remainder with highest ``score``.

    Tier sizes default to ``limit // 3`` each (so ``limit=15`` → 5 / 5 / 5).
    Pass explicit tier kwargs to override. Result is deduplicated across tiers
    and capped at ``limit``.
    """
    if queue_head is None:
        queue_head = limit // 3
    if nearest_count is None:
        nearest_count = limit // 3
    if top_score_count is None:
        top_score_count = max(0, limit - queue_head - nearest_count)
    if nearest_pool_size is None:
        nearest_pool_size = max(nearest_count * 3, 15)

    base_filters = [
        Events2Posts.is_ready.is_(None),
        Events2Posts.status == "ReadyToPost",
    ]

    selected: list = []
    seen_ids: set = set()

    def _take(rows, cap=None):
        for row in rows:
            if cap is not None and len(selected) >= cap:
                break
            if row.id in seen_ids:
                continue
            seen_ids.add(row.id)
            selected.append(row)

    # Tier 1: queue head — events about to be posted that still need AI prep.
    if queue_head > 0:
        rows = (
            db.query(Events2Posts)
            .filter(*base_filters, Events2Posts.queue.isnot(None))
            .order_by(asc(Events2Posts.queue))
            .limit(queue_head)
            .all()
        )
        _take(rows, cap=limit)

    # Tier 2: random sample from nearest upcoming events by from_date.
    if nearest_count > 0 and len(selected) < limit:
        now = datetime.now(timezone.utc)
        filters = list(base_filters) + [
            Events2Posts.from_date.isnot(None),
            Events2Posts.from_date >= now,
        ]
        if seen_ids:
            filters.append(~Events2Posts.id.in_(seen_ids))
        pool = (
            db.query(Events2Posts)
            .filter(*filters)
            .order_by(asc(Events2Posts.from_date))
            .limit(nearest_pool_size)
            .all()
        )
        if pool:
            sample = random.sample(pool, min(nearest_count, len(pool)))
            _take(sample, cap=limit)

    # Tier 3: fill remainder with top-scoring events.
    if top_score_count > 0 and len(selected) < limit:
        remaining = limit - len(selected)
        filters = list(base_filters) + [Events2Posts.score.isnot(None)]
        if seen_ids:
            filters.append(~Events2Posts.id.in_(seen_ids))
        rows = (
            db.query(Events2Posts)
            .filter(*filters)
            .order_by(desc(Events2Posts.score))
            .limit(min(top_score_count, remaining))
            .all()
        )
        _take(rows, cap=limit)

    event_dict_list = []
    for event in selected:
        event_data = {
            field: getattr(event, field)
            for field in _default_event_fields(Events2Posts)
        }
        if event.place:
            event_data["address"] = (
                f"{event.place.place_name}, {event.place.place_address}, "
                f"м.{event.place.place_metro}"
            )
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

    # Convert SQLAlchemy objects to Event objects
    result = [Event.from_database(event) for event in events]

    return result


@db_session
def get_event_to_post_now(db):
    """
    Get events that are ready to post and scheduled within 5 minutes of current time

    Returns:
        List of events ready to post now
    """
    now = datetime.now(timezone.utc)
    events = db.query(Events2Posts).filter(
        Events2Posts.status == 'ReadyToPost',
        Events2Posts.post_date.between(
            now - timedelta(minutes=5),
            now + timedelta(minutes=5)
        )
    ).order_by(Events2Posts.queue).all()

    if not events:
        return None

    # Convert SQLAlchemy objects to Event objects
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
        {field: getattr(event, field) for field in (params.fields or _default_event_fields(EventsNotApproved))}
        for event in events
    ]

    return result


@db_session
def update_not_approved_events_set_approved(db, event_ids=[]):
    db.query(EventsNotApproved)\
        .filter(EventsNotApproved.id.in_(event_ids))\
        .update({'approved': 1, 'status': 'approved'})


@db_session
def update_expired_events(db, date):
    """Transition expired ReadyToPost events to a terminal status.

    - ``is_ready = True``  → ``'Posted'`` — the event was prepared for publication
      but its date has passed. Counted in place statistics.
    - ``is_ready`` IS NULL / False → ``'Expired'`` — the event was never prepared
      by AI, nothing to post; kept as a separate status to avoid polluting
      the "published" analytics.
    """
    expired_filter = and_(
        Events2Posts.to_date < date,
        Events2Posts.status == 'ReadyToPost',
    )

    posted_count = (
        db.query(Events2Posts)
        .filter(expired_filter, Events2Posts.is_ready.is_(True))
        .update({'status': 'Posted', 'post_date': None}, synchronize_session=False)
    )
    expired_count = (
        db.query(Events2Posts)
        .filter(
            expired_filter,
            or_(Events2Posts.is_ready.is_(False), Events2Posts.is_ready.is_(None)),
        )
        .update({'status': 'Expired', 'post_date': None}, synchronize_session=False)
    )

    return {'posted': posted_count, 'expired': expired_count}


@db_session
def remove_old_not_approved_events(db, date):
    db.query(EventsNotApproved) \
        .filter(
            func.coalesce(EventsNotApproved.to_date, EventsNotApproved.from_date) < date
        ) \
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


@db_session
def add_events_to_post(db, events: List[Event], explored_date: datetime, queue_increase=2):
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
    value = int(get_last_queue_value(db))

    def func(value=value, queue_increase=queue_increase):
        while True:
            value += queue_increase
            yield value

    queue_value_gen = func()

    # Load keywords once for the whole batch — avoids one DB query per event.
    place_keywords = _load_place_keywords(db)
    scoring_cfg = getattr(settings, "scoring", {})
    window = scoring_cfg.get("repetition_window_days", 14)
    recent_titles = get_recent_event_titles(db, days=window)
    place_counts = get_place_post_counts(db)
    place_cat_queue = get_place_category_queue_counts(db)
    date_counts = get_date_event_counts(db, days=scoring_cfg.get("date_scarcity_window_days", 10))

    list_inserted_ids = []
    for event in events:

        event_dict = event.to_dict()
        event_dict.update({
            'status': 'ReadyToPost',
            'queue': next(queue_value_gen),
            'explored_date': explored_date
        })

        if not event_dict.get('place_id'):
            search = " ".join(filter(None, [event_dict.get('address'), event_dict.get('title')]))
            event_dict['place_id'] = _match_place(search, place_keywords)

        _apply_scoring(event_dict, event_dict.get('place_id'), recent_titles, place_counts, place_cat_queue, date_counts)

        dup_id = find_exhibition_duplicate(
            db=db,
            title=event_dict.get('title', ''),
            place_id=event_dict.get('place_id'),
            main_category_id=event_dict.get('main_category_id'),
        )
        if dup_id:
            continue

        new_event = create_event(db, event_dict, Events2Posts)
        if new_event and 'id' in new_event:
            list_inserted_ids.append(new_event['id'])
            recent_titles.append(event_dict.get('title', ''))
            # Update in-memory counter so subsequent events in this batch feel the saturation
            pid = event_dict.get('place_id')
            cid = resolve_category_id(
                event_dict.get('main_category_id'),
                event_dict.get('category'),
                event_dict.get('title', ''),
                event_dict.get('full_text', ''),
            )
            if pid and cid is not None:
                key = (pid, cid)
                place_cat_queue[key] = place_cat_queue.get(key, 0) + 1

    return list_inserted_ids


@db_session
def add_events(db, events: List[Event], explored_date: datetime, table: str = "events_eventsnotapprovednew"):
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
        raise ValueError(f"Unknown table: {table}")

    place_keywords = _load_place_keywords(db)
    scoring_cfg = getattr(settings, "scoring", {})
    window = scoring_cfg.get("repetition_window_days", 14)
    recent_titles = get_recent_event_titles(db, days=window)
    place_counts = get_place_post_counts(db)
    place_cat_queue = get_place_category_queue_counts(db)
    date_counts = get_date_event_counts(db, days=scoring_cfg.get("date_scarcity_window_days", 10))

    list_inserted_ids = []
    for event in events:
        event_dict = event.to_dict()

        event_dict.update({
            'approved': False,
            'explored_date': explored_date,
        })

        # Place matching for EventsNotApproved
        if not event_dict.get('place_id'):
            search = " ".join(
                filter(None, [event_dict.get('address'), event_dict.get('title')])
            )
            event_dict['place_id'] = _match_place(search, place_keywords)

        _apply_scoring(event_dict, event_dict.get('place_id'), recent_titles, place_counts, place_cat_queue, date_counts)

        new_event = create_event(db, event_dict, model)
        if new_event and 'id' in new_event:
            list_inserted_ids.append(new_event['id'])
            recent_titles.append(event_dict.get('title', ''))

    return list_inserted_ids


@db_session
def set_status(db: object, event_id: str, status: str, error_message: str = None) -> None:
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

    error_message : str, optional
        Error details to store in score_breakdown['error'].
    """
    import json as _json

    event = db.query(Events2Posts).filter_by(event_id=event_id).first()
    if event:
        event.status = status
        if error_message:
            existing = {}
            if event.score_breakdown:
                try:
                    existing = _json.loads(event.score_breakdown) if isinstance(event.score_breakdown, str) else dict(event.score_breakdown)
                except Exception:
                    pass
            existing['error'] = {'message': error_message, 'status': status}
            event.score_breakdown = existing


@db_session
def set_post_url(db: object, event_id: str, post_url: str) -> None:
    db.query(Events2Posts).filter_by(event_id=event_id).update({"post_url": post_url})


@db_session
def get_last_queue_value(db) -> int:
    result = db.query(Events2Posts.queue).filter_by(status='ReadyToPost').order_by(Events2Posts.queue.desc()).first()
    last_queue_value = result[0] if result and result[0] is not None else 0
    return last_queue_value


@db_session
def get_events_missing_images(db, event_ids: list = [], limit: int = 50) -> List[dict]:
    query = db.query(Events2Posts)

    if event_ids:
        query = query.filter(Events2Posts.id.in_(event_ids))
    else:
        query = query.filter(Events2Posts.status == 'ReadyToPost')

    query = query.filter(
        (Events2Posts.image_upload == None) | (Events2Posts.image_upload == ''),
        (Events2Posts.image != None) | (Events2Posts.image != ''),
    )

    if not limit:
        limit = 50

    events = query.limit(limit)

    events_wo_images = []
    for event in events:
        events_wo_images.append({'id': event.id, 'event_id': event.event_id, 'image': event.image})
    return events_wo_images


@db_session
def update_image_events(db, event_id: str, image_url: str, s3_key: str = None) -> None:
    update_fields = {"image": image_url}
    if s3_key:
        update_fields["image_upload"] = s3_key
    db.query(Events2Posts).filter_by(id=event_id).update(update_fields)

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
    now = datetime.now(timezone.utc)

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


### Scoring helpers ###
######–--START--–######


@db_session
def find_exhibition_duplicate(
    db,
    title: str,
    place_id: int,
    main_category_id: int,
    lookup_days: int = 180,
    threshold: float = 0.85,
) -> int:
    """Returns Events2Posts.id of an existing exhibition (category=11) at the same place
    with a similar title (Jaccard > threshold) seen within `lookup_days`. 0 if no dup.

    Timepad re-publishes the same exhibition with new dates; this helper catches such
    duplicates by place + title similarity so we don't post the same thing repeatedly.
    """
    from .scoring import _is_exhibition_by_id, title_similarity

    if not _is_exhibition_by_id(main_category_id):
        return 0
    if not title or not place_id:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookup_days)
    candidates = (
        db.query(Events2Posts.id, Events2Posts.title)
        .filter(
            Events2Posts.main_category_id == 11,
            Events2Posts.place_id == place_id,
            Events2Posts.status.in_(('Posted', 'ReadyToPost', 'OnlyApi')),
            Events2Posts.explored_date >= cutoff,
        )
        .all()
    )
    for existing_id, existing_title in candidates:
        if existing_title and title_similarity(title, existing_title) > threshold:
            return existing_id
    return 0


@db_session
def get_recent_event_titles(db, days: int = 14) -> List[str]:
    """Return titles from both tables for the last N days (repetition check)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    titles_approved = (
        db.query(Events2Posts.title)
        .filter(Events2Posts.explored_date >= cutoff)
        .all()
    )
    titles_not_approved = (
        db.query(EventsNotApproved.title)
        .filter(EventsNotApproved.explored_date >= cutoff)
        .all()
    )
    return [t[0] for t in titles_approved + titles_not_approved if t[0]]


@db_session
def get_place_post_counts(db) -> dict:
    """Return {place_id: count} of Posted events per place (for reputation)."""
    rows = (
        db.query(Events2Posts.place_id, func.count(Events2Posts.id))
        .filter(
            Events2Posts.place_id.isnot(None),
            Events2Posts.status == "Posted",
        )
        .group_by(Events2Posts.place_id)
        .all()
    )
    return {place_id: cnt for place_id, cnt in rows}


@db_session
def get_date_event_counts(db, days: int = 10) -> dict:
    """Return {date: count} of events per from_date within the next N days.

    Counts Events2Posts (Posted/ReadyToPost) + EventsNotApproved (all statuses).
    The combined count tells us whether the system has data for that date at all
    (used to avoid boosting events for dates that simply haven't been scraped yet).
    """
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today + timedelta(days=days)

    rows_e2p = (
        db.query(Events2Posts.from_date)
        .filter(
            Events2Posts.from_date >= today,
            Events2Posts.from_date < cutoff,
            Events2Posts.status.in_(["Posted", "ReadyToPost", "Expired", "OnlyApi"]),
        )
        .all()
    )
    rows_na = (
        db.query(EventsNotApproved.from_date)
        .filter(
            EventsNotApproved.from_date >= today,
            EventsNotApproved.from_date < cutoff,
        )
        .all()
    )

    counts = {}
    for (dt,) in rows_e2p + rows_na:
        if dt:
            d = dt.date() if hasattr(dt, "date") else dt
            counts[d] = counts.get(d, 0) + 1
    return counts


@db_session
def get_place_category_queue_counts(db) -> dict:
    """Return {(place_id, category_id): count} of ReadyToPost events per place+category.

    Used to detect venue/genre saturation in the posting queue.
    """
    rows = (
        db.query(Events2Posts.place_id, Events2Posts.main_category_id, func.count(Events2Posts.id))
        .filter(
            Events2Posts.place_id.isnot(None),
            Events2Posts.main_category_id.isnot(None),
            Events2Posts.status == "ReadyToPost",
        )
        .group_by(Events2Posts.place_id, Events2Posts.main_category_id)
        .all()
    )
    return {(place_id, cat_id): cnt for place_id, cat_id, cnt in rows}


def _get_scoring_config() -> dict:
    """Return scoring config merged with adaptive overrides from Redis."""
    base = getattr(settings, "scoring", {})
    try:
        from .celery_app import redis_client
        adaptive = load_from_redis(redis_client)
        return merge_adaptive_config(base, adaptive)
    except Exception:
        return base


def _apply_scoring(
    event_dict: dict,
    place_id,
    recent_titles: List[str],
    place_post_counts: dict,
    place_category_queue_counts: dict = None,
    date_event_counts: dict = None,
):
    """Calculate score and write score/score_breakdown into event_dict."""
    scoring_config = _get_scoring_config()
    breakdown = calculate_score(
        event_data=event_dict,
        existing_titles=recent_titles,
        place_id=place_id,
        scoring_config=scoring_config,
        place_post_counts=place_post_counts,
        place_category_queue_counts=place_category_queue_counts,
        date_event_counts=date_event_counts,
    )
    event_dict["score"] = breakdown.total
    event_dict["score_breakdown"] = breakdown.to_json()


@db_session
def recalculate_event_score(db, event_id: int, table: str = "events_events2post") -> dict:
    """Recalculate score for a single event (after AI fills place/category).

    Returns
    -------
    dict
        {"score": int, "score_breakdown": str} or None.
    """
    model = MODEL_REGISTRY.get(table)
    if not model:
        return None

    event = db.query(model).filter_by(id=event_id).first()
    if not event:
        return None

    event_dict = {
        col.name: getattr(event, col.name) for col in event.__table__.columns
    }

    scoring_config = _get_scoring_config()
    window = scoring_config.get("repetition_window_days", 14)
    recent_titles = get_recent_event_titles(days=window)
    place_counts = get_place_post_counts()
    place_cat_queue = get_place_category_queue_counts()
    date_counts = get_date_event_counts(days=scoring_config.get("date_scarcity_window_days", 10))

    breakdown = calculate_score(
        event_data=event_dict,
        existing_titles=recent_titles,
        place_id=event_dict.get("place_id"),
        scoring_config=scoring_config,
        place_post_counts=place_counts,
        place_category_queue_counts=place_cat_queue,
        date_event_counts=date_counts,
    )

    event.score = breakdown.total
    event.score_breakdown = breakdown.to_json()
    db.commit()

    return {"score": breakdown.total, "score_breakdown": breakdown.to_json()}


@db_session
def recalculate_scores_bulk(
    db,
    table: str = "events_eventsnotapprovednew",
    ids: list[int] = None,
    only_null: bool = True,
) -> dict:
    """Resolve place_id (if missing) and recalculate score for a batch of events.

    Parameters
    ----------
    table : str
        "events_events2post" or "events_eventsnotapprovednew"
    ids : list[int] | None
        If given — process only these IDs; otherwise process all matching the filter.
    only_null : bool
        If True — skip events that already have a score (score IS NOT NULL).

    Returns
    -------
    dict
        {"updated": int, "skipped": int}
    """
    model = MODEL_REGISTRY.get(table)
    if not model:
        return {"error": f"Unknown table: {table}", "updated": 0, "skipped": 0}

    query = db.query(model)
    if ids:
        query = query.filter(model.id.in_(ids))
    if only_null:
        query = query.filter(model.score.is_(None))

    events = query.all()
    if not events:
        return {"updated": 0, "skipped": 0}

    place_keywords = _load_place_keywords(db)
    scoring_config = _get_scoring_config()
    window = scoring_config.get("repetition_window_days", 14)
    recent_titles = get_recent_event_titles(days=window)
    place_counts = get_place_post_counts()
    place_cat_queue = get_place_category_queue_counts()
    date_counts = get_date_event_counts(days=scoring_config.get("date_scarcity_window_days", 10))

    updated = 0
    skipped = 0
    for event in events:
        try:
            # Resolve place_id if missing
            if not event.place_id:
                search_parts = [
                    getattr(event, "address", None),
                    getattr(event, "title", None),
                ]
                search = " ".join(filter(None, search_parts))
                if search:
                    event.place_id = _match_place(search, place_keywords)

            event_dict = {
                col.name: getattr(event, col.name) for col in event.__table__.columns
            }
            breakdown = calculate_score(
                event_data=event_dict,
                existing_titles=recent_titles,
                place_id=event.place_id,
                scoring_config=scoring_config,
                place_post_counts=place_counts,
                place_category_queue_counts=place_cat_queue,
                date_event_counts=date_counts,
            )

            event.score = breakdown.total
            event.score_breakdown = breakdown.to_json()
            recent_titles.append(event_dict.get("title", ""))
            updated += 1
        except Exception:
            skipped += 1

    db.commit()
    return {"updated": updated, "skipped": skipped}


@db_session
def reject_event_by_ai(db, event_id: int, reason: str = None):
    """Mark an Events2Posts event as rejected by AI during prepare step.

    Stores the rejection reason in score_breakdown JSONB and sets status to 'rejected'.
    """
    import json as _json
    event = db.query(Events2Posts).filter_by(id=event_id).first()
    if not event:
        return False

    # Merge ai_review into existing score_breakdown
    existing = {}
    if event.score_breakdown:
        try:
            existing = _json.loads(event.score_breakdown) if isinstance(event.score_breakdown, str) else dict(event.score_breakdown)
        except Exception:
            pass
    existing['ai_review'] = {'relevant': False, 'reason': reason or ''}
    event.score_breakdown = existing
    event.status = 'Rejected'
    event.is_ready = False
    db.commit()
    return True


@db_session
def get_adaptive_scoring_data(db, days: int = 30) -> dict:
    """Collect positive and negative events for adaptive scoring.

    Positive: Events2Posts (all — they passed moderation).
    Negative: EventsNotApproved with rejected/spam/not_event/duplicate status,
              or 'new' older than 7 days (ignored).

    Returns {"positive": [dict], "negative": [dict]}
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Positive: all Events2Posts created in the window
    pos_query = db.query(Events2Posts).filter(
        Events2Posts.explored_date >= cutoff,
    )
    positive = []
    for e in pos_query:
        positive.append({
            col.name: getattr(e, col.name) for col in e.__table__.columns
        })

    # Negative: explicitly rejected + stale 'new'
    neg_query = db.query(EventsNotApproved).filter(
        EventsNotApproved.explored_date >= cutoff,
        or_(
            EventsNotApproved.status.in_(["rejected", "not_event", "spam", "duplicate"]),
            and_(
                EventsNotApproved.status == "new",
                EventsNotApproved.explored_date < stale_cutoff,
            ),
        ),
    )
    negative = []
    for e in neg_query:
        negative.append({
            col.name: getattr(e, col.name) for col in e.__table__.columns
        })

    return {"positive": positive, "negative": negative}


######–--FINISH--–######


### Place lookup ###
######–-START-–######

_MIN_KEYWORD_LENGTH = 4


def _load_place_keywords(db) -> list[tuple[str, int]]:
    """Load all usable PlaceKeywords from DB, sorted longest-first.

    Returns list of (keyword_lower, place_id) tuples ready for Python matching.
    Helper — always called with db from outer @db_session function.
    """
    rows = (
        db.query(PlaceKeyword.place_keyword, PlaceKeyword.place_id)
        .filter(func.length(PlaceKeyword.place_keyword) >= _MIN_KEYWORD_LENGTH)
        .order_by(func.length(PlaceKeyword.place_keyword).desc())
        .all()
    )
    return [(kw.lower(), place_id) for kw, place_id in rows]


def _match_place(search_text: str, keywords: list[tuple[str, int]]):
    """Return place_id for the first (longest) keyword found in search_text.

    Pure Python substring check — O(n) over pre-sorted keyword list.
    keywords must be sorted longest-first (as returned by _load_place_keywords).
    """
    text = search_text.lower()
    for kw, place_id in keywords:
        if kw in text:
            return place_id
    return None


@db_session
def find_place_by_address(db, address: str, title: str = None):
    """Find place_id for a single event by matching PlaceKeywords.

    Use this for one-off lookups (e.g. create_event_to_post).
    For batch inserts use _load_place_keywords() + _match_place() directly.
    """
    search_parts = [p for p in (address, title) if p]
    if not search_parts:
        return None
    keywords = _load_place_keywords(db)
    return _match_place(" ".join(search_parts), keywords)


def _resolve_place(db, event_data: dict, place_keywords=None):
    """Resolve a Place for an event: first by place_id, then by address.

    Returns:
        Place ORM object or None.
    """
    if event_data.get('place_id'):
        place = db.query(Place).get(event_data['place_id'])
        if place:
            return place

    search_text = ' '.join(filter(None, [event_data.get('address'), event_data.get('title')]))
    if not search_text:
        return None

    if place_keywords is None:
        place_keywords = _load_place_keywords(db)
    place_id = _match_place(search_text, place_keywords)
    if place_id:
        return db.query(Place).get(place_id)
    return None


def _place_to_view(place):
    """Convert an ORM Place to a PlaceView for PostHelper."""
    from .helper.post_helper import PlaceView
    if place is None:
        return None
    return PlaceView(
        id=place.id,
        name=place.place_name or '',
        address=place.place_address or '',
        url=place.place_url or '',
        metro=place.place_metro or '',
        schedule_str=place.get_schedule_str(),
    )


def _resolve_place_view(db, event_data: dict, place_keywords=None):
    """Resolve a Place and return a PlaceView (or None)."""
    place = _resolve_place(db, event_data, place_keywords)
    return _place_to_view(place)


OTHER_CATEGORY_NAME = "Other"
UNCATEGORIZED_CATEGORY_ID = 2  # 'Без категории' — treated as fallback, re-resolved like NULL


def _get_or_create_other_category(db) -> Category:
    other = db.query(Category).filter(Category.name == OTHER_CATEGORY_NAME).first()
    if other:
        return other
    other = Category(name=OTHER_CATEGORY_NAME)
    db.add(other)
    db.flush()
    return other


def resolve_main_category_id(
    db,
    category_str: str | None,
    current_main_category_id: int | None = None,
    title: str = "",
    full_text: str = "",
    write: bool = True,
) -> int | None:
    """Port of Django Events2Post.save() + SubCategory.save() fallback.

    Rules (mirroring Django):
      1. If current_main_category_id is set AND != UNCATEGORIZED_CATEGORY_ID — keep it.
      2. Else if category_str matches a SubCategory.name — return its category_id.
         If that SubCategory has no category — attach it to Category('Other') (write).
      3. Else if category_str non-empty — create SubCategory + attach to 'Other' (write).
      4. Else (category_str empty/None) — fall back to keyword inference from title/full_text.
         Does NOT write to the DB in this branch (no name to store).

    Args:
        write: if False, only look up existing SubCategory; falls back to keyword
               guess when missing. Use for preview / no-side-effect calls.

    Returns: category_id or None.
    """
    if current_main_category_id is not None and current_main_category_id != UNCATEGORIZED_CATEGORY_ID:
        return current_main_category_id

    name = (category_str or "").strip()
    if not name:
        return resolve_category_id(
            main_category_id=None,
            category_str=None,
            title=title,
            full_text=full_text,
        )

    subcat = db.query(SubCategory).filter(SubCategory.name == name).first()
    if subcat is not None:
        if subcat.category_id is not None:
            return subcat.category_id
        if not write:
            return resolve_category_id(
                main_category_id=None,
                category_str=name,
                title=title,
                full_text=full_text,
            )
        other = _get_or_create_other_category(db)
        subcat.category_id = other.id
        db.flush()
        return other.id

    if not write:
        return resolve_category_id(
            main_category_id=None,
            category_str=name,
            title=title,
            full_text=full_text,
        )
    other = _get_or_create_other_category(db)
    subcat = SubCategory(name=name, category_id=other.id)
    db.add(subcat)
    db.flush()
    return other.id


######–-FINISH-–######

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
    db_user = db.query(DsnUser).filter(or_(DsnUser.nickname == user_data.nickname, DsnUser.email == user_data.email)).first()
    if db_user:
        return None  # User already exists

    hashed_password = get_password_hash(user_data.password)

    new_user = DsnUser(
        nickname=user_data.nickname,
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        is_active=True
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    new_user_dict = new_user.__dict__
    return new_user_dict


@db_session
def authenticate_user(db, nickname: str, password: str):
    """Login user with email and password."""

    db_user = db.query(DsnUser).filter(DsnUser.nickname == nickname).first()

    if not db_user:
        return None  # User not found

    if not verify_password(password, db_user.hashed_password):
        return None  # Wrong password
    new_user_dict = db_user.__dict__
    return new_user_dict


@db_session
def get_user_by_nickname(db, nickname: str) -> dict:
    return db.query(DsnUser).filter(DsnUser.nickname == nickname).first().__dict__


@db_session
def update_user(db, nickname: str, user_update: UserUpdate) -> dict:
    db_user = db.query(DsnUser).filter(DsnUser.nickname == nickname).first()
    if not db_user:
        return None
    for key, value in user_update.model_dump(exclude_unset=True).items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return db_user.__dict__


@db_session
def get_or_create_user_by_telegram_id(db, telegram_id: int, telegram_user_info: dict):
    """Looking for user by Telegram_ID or making a new user."""

    db_user = db.query(DsnUser).filter(DsnUser.telegram_id == telegram_id).first()

    if db_user:
        return db_user.__dict__

    full_name = ''
    if telegram_user_info.get('first_name', ''):
        full_name += telegram_user_info.get('first_name', '')
    if telegram_user_info.get('last_name', ''):
        if full_name:
            full_name += ' '
        full_name += telegram_user_info.get('last_name', '')
    nickname = 'tg_' + str(telegram_id)
    if telegram_user_info.get('username'):
        nickname = 'tg_' + telegram_user_info.get('username')

    hashed_password = get_password_hash(nickname+full_name)

    new_user = DsnUser(
        telegram_id=telegram_id,
        full_name=full_name,
        nickname=nickname,
        email=f"{telegram_id}@tg.me",
        hashed_password=hashed_password,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user.__dict__


####––––––FINISH––––––######


###### USER Functions ######
######–----START----–#######

@db_session
def add_event_to_user(db, user_id, event_id):
    user_event = DsnUserEvent(
        user_id=user_id,
        event_id=event_id,
        remind_datetime=None,
        remind_sent=False
    )
    db.add(user_event)
    db.commit()
    db.refresh(user_event)
    return user_event.__dict__


@db_session
def remove_event_from_user(db, user_id, event_id):
    user_event = db.query(DsnUserEvent).filter(
        DsnUserEvent.user_id == user_id,
        DsnUserEvent.event_id == event_id
    ).first()
    if user_event:
        db.delete(user_event)
        db.commit()
        return True
    return False


@db_session
def get_user_favourite_events(db, user_id):
    query = (
        db.query(DsnUserEvent)
            .options(joinedload(DsnUserEvent.event))
            .filter(DsnUserEvent.user_id == user_id)
    )

    result = []
    for user_event in query.all():
        event = user_event.event

        result.append(event.__dict__)
    return result


####––––––FINISH––––––######


###### EventsNotApproved Functions ######
######–--------START--------–#######

# Sources that contain raw text requiring AI analysis.
# Ticket platforms (timepad, radario, etc.) already provide structured data.
AI_SOURCES = ["telegram"]


@db_session
def get_not_approved_events_for_processing(db, limit: int = 50, source: str = None, sources: List[str] = None) -> List[dict]:
    """
    Retrieve events with status 'new' for AI processing.

    Parameters
    ----------
    limit : int
        Maximum number of events.
    source : str, optional
        Filter by a single source.
    sources : List[str], optional
        Filter by multiple sources.
        Defaults to AI_SOURCES (telegram, instagram, vk).

    Returns
    -------
    List[dict]
        List of events with fields: id, text, image, source.
    """
    query = db.query(EventsNotApproved).filter(
        EventsNotApproved.status == 'new',
        EventsNotApproved.full_text.isnot(None)
    )

    if source:
        query = query.filter(EventsNotApproved.source == source)
    elif sources:
        query = query.filter(EventsNotApproved.source.in_(sources))
    else:
        query = query.filter(EventsNotApproved.source.in_(AI_SOURCES))

    events = query.limit(limit).all()

    return [
        {"id": e.id, "text": e.full_text, "image": e.image, "source": e.source}
        for e in events
    ]


@db_session
def update_not_approved_event_status(db, event_id: int, status: str) -> bool:
    """
    Update the status of an event in EventsNotApproved.

    Parameters
    ----------
    event_id : int
        Event ID.
    status : str
        New status: 'new', 'extracted', 'not_event', 'pending', 'approved', 'rejected', 'spam', 'duplicate'.

    Returns
    -------
    bool
        True if updated successfully.
    """
    event = db.query(EventsNotApproved).filter_by(id=event_id).first()
    if event:
        event.status = status
        db.commit()
        return True
    return False


def _enrich_not_approved_event(db, event, enriched_data: dict) -> None:
    """Apply enriched fields to an already-loaded event. Does not commit."""
    allowed_fields = {
        "title", "address", "price", "price_int", "category",
        "from_date", "to_date", "url", "ticket_url",
    }

    for key, value in enriched_data.items():
        if key in allowed_fields and value is not None:
            setattr(event, key, value)

    # Resolve place_id from enriched address
    if enriched_data.get("address") and not event.place_id:
        search = " ".join(
            filter(None, [enriched_data.get("address"), enriched_data.get("title")])
        )
        keywords = _load_place_keywords(db)
        event.place_id = _match_place(search, keywords)


@db_session
def enrich_not_approved_event(db, event_id: int, enriched_data: dict) -> bool:
    """Update EventsNotApproved with AI-enriched data.

    Only non-empty values overwrite existing fields.
    """
    event = db.query(EventsNotApproved).filter_by(id=event_id).first()
    if not event:
        return False

    _enrich_not_approved_event(db, event, enriched_data)
    db.commit()
    return True


@db_session
def bulk_update_not_approved_status(db, updates: List[dict]) -> int:
    """
    Bulk update of statuses and (optionally) enriched data.

    Parameters
    ----------
    updates : List[dict]
        List of updates: [{"id": 1, "status": "extracted", "enriched": {...}}, ...]
        enriched — optional dict with fields to update.

    Returns
    -------
    int
        Number of updated records.
    """
    updated = 0
    for item in updates:
        event = db.query(EventsNotApproved).filter_by(id=item["id"]).first()
        if event:
            event.status = item["status"]
            enriched = item.get("enriched")
            if enriched:
                _enrich_not_approved_event(db, event, enriched)
            updated += 1
    db.commit()
    return updated


@db_session
def get_not_approved_event_by_id(db, event_id: int) -> dict:
    """Retrieve an event by ID."""
    event = db.query(EventsNotApproved).filter_by(id=event_id).first()
    if event:
        return {
            "id": event.id,
            "event_id": event.event_id,
            "title": event.title,
            "full_text": event.full_text,
            "image": event.image,
            "source": event.source,
            "status": event.status,
            "url": event.url,
            "from_date": event.from_date,
            "to_date": event.to_date,
            "price": event.price,
            "address": event.address,
            "category": event.category
        }
    return None


@db_session
def create_not_approved_event(db, event_data: dict) -> int:
    """Create a record in EventsNotApproved."""
    event_data.setdefault("status", "new")
    result = create_event(db, event_data, EventsNotApproved)
    return result["id"]


@db_session
def create_event_to_post(db, event_data: dict) -> int:
    """Create a record in Events2Posts with an automatic queue value."""
    if "queue" not in event_data:
        last_q = db.query(Events2Posts.queue).filter_by(status='ReadyToPost').order_by(Events2Posts.queue.desc()).first()
        event_data["queue"] = (last_q[0] if last_q and last_q[0] is not None else 0) + 2
    event_data.setdefault("status", "draft")
    event_data.setdefault("is_ready", event_data["status"] == "ReadyToPost")
    if not event_data.get("place_id"):
        event_data["place_id"] = find_place_by_address(
            address=event_data.get("address"),
            title=event_data.get("title"),
        )
    main_category_id = resolve_main_category_id(
        db,
        category_str=event_data.get("category"),
        current_main_category_id=event_data.get("main_category_id"),
        title=event_data.get("title", ""),
        full_text=event_data.get("full_text", ""),
    )
    if main_category_id is not None:
        event_data["main_category_id"] = main_category_id
    result = create_event(db, event_data, Events2Posts)
    return result["id"]


@db_session
def create_events_to_posts_bulk(db, events_data: List[dict]) -> List[int]:
    """Create multiple records in Events2Posts."""
    last_q = db.query(Events2Posts.queue).filter_by(status='ReadyToPost').order_by(Events2Posts.queue.desc()).first()
    queue_value = (last_q[0] if last_q and last_q[0] is not None else 0) + 2
    created_ids = []
    for event_data in events_data:
        event_data.setdefault("queue", queue_value)
        event_data.setdefault("status", "draft")
        event_data.setdefault("is_ready", event_data["status"] == "ReadyToPost")
        main_category_id = resolve_main_category_id(
            db,
            category_str=event_data.get("category"),
            current_main_category_id=event_data.get("main_category_id"),
            title=event_data.get("title", ""),
            full_text=event_data.get("full_text", ""),
        )
        if main_category_id is not None:
            event_data["main_category_id"] = main_category_id
        event = Events2Posts(**event_data)
        db.add(event)
        db.flush()
        created_ids.append(event.id)
        queue_value += 2
    db.commit()
    return created_ids


@db_session
def move_approved_to_posts(db, status: str = 'ReadyToPost') -> List[int]:
    """Move events with status 'approved' from NotApproved to Events2Posts and delete them from NotApproved.

    Args:
        status: target status in Events2Posts (default 'ReadyToPost'; e.g. 'OnlyApi'
                to push events to the API-only bucket without channel publication).
    """
    from .helper.post_helper import PostHelper

    skip_fields = {'id', 'status', 'approved'}
    source_columns = {c.key for c in EventsNotApproved.__table__.columns}
    target_columns = {c.key for c in Events2Posts.__table__.columns}
    shared_fields = (source_columns & target_columns) - skip_fields

    existing_event_ids = {
        eid for (eid,) in db.query(Events2Posts.event_id).all() if eid
    }

    candidates = (
        db.query(EventsNotApproved)
        .filter(EventsNotApproved.status == 'approved')
        .all()
    )

    last_q = db.query(Events2Posts.queue).filter_by(status='ReadyToPost').order_by(Events2Posts.queue.desc()).first()
    queue_value = (last_q[0] if last_q and last_q[0] is not None else 0) + 2
    place_keywords = _load_place_keywords(db)
    moved_ids = []

    for event in candidates:
        if event.event_id in existing_event_ids:
            db.delete(event)
            continue

        event_data = {
            field: getattr(event, field)
            for field in shared_fields
            if getattr(event, field, None) is not None
        }
        event_data['status'] = status
        event_data['queue'] = queue_value
        queue_value += 2

        # Resolve place
        place_view = _resolve_place_view(db, event_data, place_keywords)
        if place_view:
            event_data['place_id'] = place_view.id

        # prepared_text = original post; a new post is generated below
        event_data['prepared_text'] = event_data.get('post')
        helper = PostHelper(event_data, place=place_view)
        event_data['post'] = helper.post_markdown()
        main_category_id = resolve_main_category_id(
            db,
            category_str=event_data.get('category'),
            current_main_category_id=event_data.get('main_category_id'),
            title=event_data.get('title', ''),
            full_text=event_data.get('full_text', ''),
        )
        if main_category_id is not None:
            event_data['main_category_id'] = main_category_id
        price_int = PostHelper.price_int(event_data.get('price', ''))
        if price_int is not None:
            event_data['price_int'] = price_int

        new_event = Events2Posts(**event_data)
        db.add(new_event)
        db.flush()
        moved_ids.append(new_event.id)

        db.delete(event)
        existing_event_ids.add(event.event_id)

    db.commit()
    return moved_ids


@db_session
def remake_event_post(db, event_id: int, save: bool = False) -> dict:
    """Regenerate the post text for an event in Events2Posts.

    Args:
        event_id: ID of the event in Events2Posts.
        save: True — update the post in the DB; False — return the preview only.

    Returns:
        dict with the regenerated post and resolved place_id.
    """
    from .helper.post_helper import PostHelper

    event = db.query(Events2Posts).filter_by(id=event_id).first()
    if not event:
        return None

    event_data = {
        c.key: getattr(event, c.key)
        for c in Events2Posts.__table__.columns
        if getattr(event, c.key, None) is not None
    }
    place_view = _resolve_place_view(db, event_data)
    if place_view:
        event_data['place_id'] = place_view.id

    helper = PostHelper(event_data, place=place_view)
    new_post = helper.post_markdown()
    place_id = place_view.id if place_view else event.place_id
    main_category_id = resolve_main_category_id(
        db,
        category_str=event_data.get('category'),
        current_main_category_id=event_data.get('main_category_id'),
        title=event_data.get('title', ''),
        full_text=event_data.get('full_text', ''),
    )
    price_int = PostHelper.price_int(event.price) if event.price else None

    if save:
        event.post = new_post
        if place_id:
            event.place_id = place_id
        if main_category_id is not None:
            event.main_category_id = main_category_id
        if price_int is not None:
            event.price_int = price_int
        db.commit()

    return {
        "post": new_post,
        "place_id": place_id,
        "main_category_id": main_category_id,
        "price_int": price_int,
        "event_id": event_id,
        "saved": save,
    }


def _make_post_pipeline(
    db,
    event_data: dict,
    place_keywords=None,
    write_subcategory: bool = False,
) -> dict:
    """Shared pipeline used by single and bulk post-creation paths.

    Mutates event_data in place with resolved place_id (if any) and returns
    the computed values. write_subcategory controls whether the category
    resolver may insert new SubCategory rows.
    """
    from .helper.post_helper import PostHelper

    place_view = _resolve_place_view(db, event_data, place_keywords)
    if place_view:
        event_data['place_id'] = place_view.id

    helper = PostHelper(event_data, place=place_view)
    post = helper.post_markdown()
    main_category_id = resolve_main_category_id(
        db,
        category_str=event_data.get('category'),
        current_main_category_id=event_data.get('main_category_id'),
        title=event_data.get('title', ''),
        full_text=event_data.get('full_text', ''),
        write=write_subcategory,
    )
    price_int = PostHelper.price_int(event_data.get('price', ''))

    return {
        "post": post,
        "place_id": place_view.id if place_view else None,
        "main_category_id": main_category_id,
        "price_int": price_int,
    }


@db_session
def make_post_from_dict(db, event_data: dict) -> dict:
    """Generate a post from an arbitrary dict (preview only, no DB write).

    Args:
        event_data: dict with event fields (title, full_text, from_date, to_date,
                    address, price, url, etc.)

    Returns:
        dict with post, place_id, main_category_id, price_int.
    """
    return _make_post_pipeline(db, dict(event_data), write_subcategory=False)


@db_session
def bulk_make_and_save_posts(
    db,
    events_data: List[dict],
    save: bool = False,
    status: str = 'ReadyToPost',
) -> List[dict]:
    """Bulk variant of make_post_from_dict (+ optional save to Events2Posts).

    Per event runs _make_post_pipeline (same as the single-item endpoint).
    If save=True — also inserts a row into Events2Posts (queue auto-assigned,
    is_ready derived from status). Per-event errors are captured and reported
    without aborting the batch.

    Args:
        events_data: list of event dicts.
        save: True — write to DB; False — preview only.
        status: target status when saving (default 'ReadyToPost').

    Returns:
        List of dicts, one per input event: {post, place_id, main_category_id,
        price_int, event_id (or None), saved, error (or None)}.
    """
    place_keywords = _load_place_keywords(db)

    queue_value = None
    if save:
        last_q = (
            db.query(Events2Posts.queue)
            .filter_by(status='ReadyToPost')
            .order_by(Events2Posts.queue.desc())
            .first()
        )
        queue_value = (last_q[0] if last_q and last_q[0] is not None else 0) + 2

    target_columns = {c.key for c in Events2Posts.__table__.columns}
    # 'id' must be auto-assigned by the DB; callers must not override it.
    insertable_columns = target_columns - {'id'}
    results: List[dict] = []

    for raw in events_data:
        try:
            event_data = dict(raw)
            pipeline = _make_post_pipeline(
                db, event_data, place_keywords=place_keywords, write_subcategory=save,
            )

            entry = {**pipeline, "event_id": None, "saved": False, "error": None}

            if save:
                row_data = {k: v for k, v in event_data.items() if k in insertable_columns}
                row_data['post'] = pipeline['post']
                if pipeline['main_category_id'] is not None:
                    row_data['main_category_id'] = pipeline['main_category_id']
                if pipeline['price_int'] is not None:
                    row_data['price_int'] = pipeline['price_int']
                row_data.setdefault('status', status)
                row_data.setdefault('queue', queue_value)
                row_data.setdefault('is_ready', row_data['status'] == 'ReadyToPost')
                queue_value = (queue_value or 0) + 2

                new_event = Events2Posts(**row_data)
                db.add(new_event)
                db.flush()
                entry["event_id"] = new_event.id
                entry["saved"] = True

            results.append(entry)
        except Exception as e:
            results.append({
                "post": None,
                "place_id": None,
                "main_category_id": None,
                "price_int": None,
                "event_id": None,
                "saved": False,
                "error": str(e),
            })

    if save:
        db.commit()
    return results


@db_session
def auto_promote_high_score_events(
    db,
    min_score: int = 70,
    limit: int = 20,
    uncategorized_min_score: int = 80,
    social_min_score: int = 80,
    status: str = 'ReadyToPost',
) -> List[int]:
    """Move high-scoring events from NotApproved to Events2Posts (draft).

    Selects events with score >= min_score, from_date in the future,
    status 'new' or 'extracted', and not yet present in Events2Posts.

    uncategorized_min_score: threshold for events without a category or with "Без категории"
    social_min_score: threshold for events from social networks (vk, telegram, instagram)
    status: target status in Events2Posts (default 'ReadyToPost'; pass 'OnlyApi'
            to bypass the channel and expose events only via the API).
    """
    from .helper.post_helper import PostHelper

    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)
    _social_sources = ['vk', 'telegram', 'instagram']

    existing_event_ids = {
        eid for (eid,) in db.query(Events2Posts.event_id).all() if eid
    }

    candidates = (
        db.query(EventsNotApproved)
        .filter(
            EventsNotApproved.score >= min_score,
            EventsNotApproved.from_date > msk_now,
            EventsNotApproved.status.in_(['new', 'extracted']),
            # No category / NULL category requires a higher score
            or_(
                and_(
                    EventsNotApproved.category.isnot(None),
                    EventsNotApproved.category != 'Без категории',
                ),
                EventsNotApproved.score >= uncategorized_min_score,
            ),
            # Social networks require a higher score
            or_(
                ~EventsNotApproved.source.in_(_social_sources),
                EventsNotApproved.score >= social_min_score,
            ),
        )
        .order_by(EventsNotApproved.score.desc())
        .limit(limit)
        .all()
    )

    shared_fields = [
        'event_id', 'title', 'full_text', 'post', 'image', 'price',
        'price_int', 'url', 'ticket_url', 'address', 'from_date',
        'to_date', 'category', 'source', 'place_id', 'explored_date',
        'score', 'score_breakdown',
        'embedding', 'embedding_model', 'embedding_updated_at',
    ]

    last_q = db.query(Events2Posts.queue).filter_by(status='ReadyToPost').order_by(Events2Posts.queue.desc()).first()
    queue_value = (last_q[0] if last_q and last_q[0] is not None else 0) + 2
    place_keywords = _load_place_keywords(db)
    promoted_ids = []

    for event in candidates:
        if event.event_id in existing_event_ids:
            continue

        event_data = {
            field: getattr(event, field)
            for field in shared_fields
            if getattr(event, field, None) is not None
        }
        event_data['status'] = status
        event_data['queue'] = queue_value
        queue_value += 2

        place_view = _resolve_place_view(db, event_data, place_keywords)
        if place_view:
            event_data['place_id'] = place_view.id

        event_data['prepared_text'] = event_data.get('post')
        helper = PostHelper(event_data, place=place_view)
        event_data['post'] = helper.post_markdown()
        main_category_id = resolve_main_category_id(
            db,
            category_str=event_data.get('category'),
            current_main_category_id=event_data.get('main_category_id'),
            title=event_data.get('title', ''),
            full_text=event_data.get('full_text', ''),
        )
        if main_category_id is not None:
            event_data['main_category_id'] = main_category_id
        price_int = PostHelper.price_int(event_data.get('price', ''))
        if price_int is not None:
            event_data['price_int'] = price_int

        dup_id = find_exhibition_duplicate(
            db=db,
            title=event_data.get('title', ''),
            place_id=event_data.get('place_id'),
            main_category_id=event_data.get('main_category_id'),
        )
        if dup_id:
            event.status = 'duplicate'
            existing_event_ids.add(event.event_id)
            continue

        new_event = Events2Posts(**event_data)
        db.add(new_event)
        db.flush()
        promoted_ids.append(new_event.id)

        db.delete(event)
        existing_event_ids.add(event.event_id)

    db.commit()
    return promoted_ids


@db_session
def get_mid_score_events_sample(
    db, min_score: int = 40, max_score: int = 69, sample_size: int = 10
) -> List[dict]:
    """Random sample of mid-score events for AI moderation."""
    from sqlalchemy.sql.expression import func as sql_func

    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)

    events = (
        db.query(EventsNotApproved)
        .filter(
            EventsNotApproved.score >= min_score,
            EventsNotApproved.score <= max_score,
            EventsNotApproved.from_date > msk_now,
            EventsNotApproved.status.in_(['new', 'extracted']),
        )
        .order_by(sql_func.random())
        .limit(sample_size)
        .all()
    )

    return [
        {field: getattr(e, field) for field in _default_event_fields(EventsNotApproved)}
        for e in events
    ]


@db_session
def auto_reject_low_score_events(db, max_score: int = 39) -> int:
    """Auto-reject events with a very low score."""
    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)

    count = (
        db.query(EventsNotApproved)
        .filter(
            EventsNotApproved.score.isnot(None),
            EventsNotApproved.score <= max_score,
            EventsNotApproved.from_date > msk_now,
            EventsNotApproved.status.in_(['new', 'extracted']),
        )
        .update({'status': 'rejected'}, synchronize_session=False)
    )
    db.commit()
    return count


@db_session
def distribute_event_queue(db, protect_first: int = 10) -> int:
    """Reorder the queue for ReadyToPost events with variety.

    The first protect_first events (by queue) are left untouched.
    The rest are reordered: round-robin by category,
    within a category — by urgency (from_date) and score.

    Returns:
        Number of reordered events.
    """
    from collections import defaultdict

    all_events = (
        db.query(Events2Posts)
        .filter(Events2Posts.status == 'ReadyToPost')
        .order_by(Events2Posts.queue.asc())
        .all()
    )

    if len(all_events) <= protect_first:
        return 0

    protected = all_events[:protect_first]
    to_reorder = all_events[protect_first:]

    # Base queue value — after the last protected event
    base_queue = (protected[-1].queue if protected else 0) + 2

    # Group by category
    by_category = defaultdict(list)
    for event in to_reorder:
        cat = event.category or 'Без категории'
        by_category[cat].append(event)

    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)

    # Within each category sort: most urgent (from_date soonest) and highest score first
    for cat in by_category:
        by_category[cat].sort(key=lambda e: (
            (e.from_date - msk_now).total_seconds() if e.from_date else 999999999,
            -(e.score or 0),
        ))

    # Round-robin by category (largest first so popular categories interleave)
    category_queues = sorted(
        by_category.values(),
        key=lambda q: -len(q),
    )

    # Additionally interleave: free/paid and different sources
    ordered = []
    while any(category_queues):
        for queue in category_queues:
            if queue:
                ordered.append(queue.pop(0))
        category_queues = [q for q in category_queues if q]

    # Assign new queue values
    for i, event in enumerate(ordered):
        event.queue = base_queue + i * 2

    db.commit()
    return len(ordered)


@db_session
def route_events_to_api(
    db,
    min_score: int = 55,
    hard_min_score: int = 35,
    low_category_ids: List[int] = None,
    far_days: int = 14,
    limit: int = 100,
    min_channel_queue: int = 20,
) -> List[int]:
    """Remove low-priority events from the channel: ReadyToPost+is_ready IS NULL → OnlyApi.

    An event is a candidate if any of the following is true:
      - score < hard_min_score (junk)
      - score < min_score AND main_category_id IN low_category_ids
      - from_date > now + far_days (too far ahead)

    Safety floor: if fewer than min_channel_queue events with
    (ReadyToPost & is_ready=True) are scheduled in the next 7 days, skip this run.

    Returns a list of IDs of the moved events.

    # TODO: optional AI prep for OnlyApi — for now we rely on the post field
    # filled by PostHelper.post_markdown() in auto_promote_high_score_events / add_events_to_post.
    """
    low_category_ids = low_category_ids or []
    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)

    channel_window_end = msk_now + timedelta(days=7)
    channel_ready_count = (
        db.query(func.count(Events2Posts.id))
        .filter(
            Events2Posts.status == 'ReadyToPost',
            Events2Posts.is_ready.is_(True),
            Events2Posts.from_date >= msk_now,
            Events2Posts.from_date < channel_window_end,
        )
        .scalar()
    )
    if channel_ready_count < min_channel_queue:
        return []

    far_cutoff = msk_now + timedelta(days=far_days)

    criteria = [Events2Posts.score < hard_min_score]
    if low_category_ids:
        criteria.append(
            and_(
                Events2Posts.score < min_score,
                Events2Posts.main_category_id.in_(low_category_ids),
            )
        )
    criteria.append(Events2Posts.from_date > far_cutoff)

    candidates = (
        db.query(Events2Posts)
        .filter(
            Events2Posts.status == 'ReadyToPost',
            Events2Posts.is_ready.is_(None),
            Events2Posts.from_date >= msk_now,
            or_(*criteria),
        )
        .order_by(asc(Events2Posts.score))
        .limit(limit)
        .all()
    )

    routed_ids = []
    for event in candidates:
        event.status = 'OnlyApi'
        event.post_date = None
        routed_ids.append(event.id)

    if routed_ids:
        db.commit()
    return routed_ids
