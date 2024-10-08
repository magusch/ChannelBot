from sqlalchemy import func

from .database.models import Events2Posts, Exhibitions

from datetime import datetime

from .database.database_orm import db_session


@db_session
def get_events_by_date_and_category(db, start_date, end_date, category: str = None, fields: list = []):
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d')


    query = db.query(Events2Posts)\
        .filter(Events2Posts.status == 'Posted') \
        .filter(
                func.date(Events2Posts.from_date) >= start_date.date(),
                func.date(Events2Posts.to_date) <= end_date.date()
            )
    # if category:
    #     query = query.filter(Events2Posts.category == category)
    events = query.all()
    result = [
        {field: getattr(event, field) for field in (fields or event.__table__.columns.keys())}
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
