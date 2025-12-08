from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

from datetime import datetime

Base = declarative_base()


class Place(Base):
    __tablename__ = 'place_place'
    id = Column(Integer, primary_key=True, index=True)
    place_name = Column(String)
    place_address = Column(String, nullable=False)
    place_url = Column(String, nullable=False)
    place_metro = Column(String, nullable=False)
    place_image = Column(String, nullable=False)
    events = relationship("Events2Posts", back_populates="place")


class Events2Posts(Base):
    __tablename__ = 'events_events2post'

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String)
    queue = Column(Integer)
    title = Column(String, nullable=False)
    full_text = Column(String, nullable=True)
    prepared_text = Column(String, nullable=True)
    post = Column(String, nullable=True)
    image = Column(String, nullable=True)
    price = Column(String, nullable=True)
    price_int = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    post_url = Column(String, nullable=True)
    url = Column(String, nullable=False)
    ticket_url = Column(String, nullable=False)
    place_id = Column(Integer, ForeignKey(f"{Place.__tablename__}.id"), nullable=True)
    place = relationship("Place", back_populates="events")

    is_ready = Column(Boolean, nullable=True)
    explored_date = Column(DateTime, nullable=True)
    post_date = Column(DateTime, nullable=True)
    from_date = Column(DateTime, nullable=True)
    to_date = Column(DateTime, nullable=True)
    address = Column(String, nullable=True)
    category = Column(String, nullable=True)
    source = Column(String, nullable=False)
    main_category_id = Column(Integer, nullable=True)

    bot_user_events = relationship("DsnBotUserEvents", back_populates="event", cascade="all, delete-orphan")


class EventsNotApproved(Base):
    __tablename__ = 'events_eventsnotapprovednew'

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String)
    approved = Column(Boolean, nullable=True)
    title = Column(String, nullable=False)
    post = Column(String, nullable=True)
    full_text = Column(String, nullable=True)
    image = Column(String, nullable=True)
    url = Column(String, nullable=False)
    ticket_url = Column(String, nullable=False)
    price = Column(String, nullable=True)
    price_int = Column(Integer, nullable=True)
    address = Column(String, nullable=True)
    explored_date = Column(DateTime, nullable=True)
    from_date = Column(DateTime, nullable=True)
    to_date = Column(DateTime, nullable=True)
    category = Column(String, nullable=True)
    source = Column(String, nullable=False)


class Exhibitions(Base):
    __tablename__ = 'exhibitions'

    post_id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    date_before = Column(DateTime, nullable=True)
    price = Column(String, nullable=True)


class DsnBotEvents(Base):
    __tablename__ = 'bot_events'
    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    post_id = Column(Integer, nullable=True)
    date_from = Column(DateTime, nullable=True)
    date_to = Column(DateTime, nullable=True)
    price = Column(String, nullable=True)


class DsnBotUserEvents(Base):
    __tablename__ = 'bot_user_events'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('bot_user.id'))
    event_id = Column(Integer, ForeignKey('events_events2post.id'))
    remind_datetime = Column(DateTime, nullable=True)
    remind_sent = Column(Boolean, nullable=True)

    user = relationship("DsnBotUser", back_populates="bot_user_events")
    event = relationship("Events2Posts", back_populates="bot_user_events")


class DsnBotUser(Base):
    __tablename__ = 'bot_user'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger)

    bot_user_events = relationship("DsnBotUserEvents", back_populates="user")


class ApiRequestLog(Base):
    __tablename__ = 'api_request_log'
    id = Column(Integer, primary_key=True, index=True)
    ip = Column(String, nullable=False)
    endpoint = Column(String, nullable=False)
    method = Column(String, nullable=False)
    status_code = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    user_agent = Column(String, nullable=True)
    request_data = Column(String, nullable=True)


# class PlaceSchedule(Base):
#     __tablename__ = 'place_placeschedule'
#     id = Column(String, primary_key=True, index=True)
#     schedule_type = Column(String)
#     weekday = Column(Integer, nullable=True)
#     date = Column(Date, nullable=True)
#     open_time = Column(Time, nullable=True)
#     close_time = Column(Time, nullable=True)
#     place_id = Column(ForeignKey(Place))

# AUTH models

class DsnUser(Base):
    __tablename__ = "dsn_user"

    id = Column(Integer, primary_key=True)
    nickname = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    telegram_nickname = Column(String, nullable=True)

    full_name = Column(String, nullable=True)

    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)