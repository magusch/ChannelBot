from sqlalchemy import func

from .database.models import Events2Posts

from datetime import datetime

from .database.database_orm import db_session


@db_session
def get_events_by_date_and_category(db, start_date: datetime, end_date: datetime, category: str = None):
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
        {column.name: getattr(event, column.name) for column in event.__table__.columns}
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
def create_event(db, event_data):
    event = Events2Posts(**event_data)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
