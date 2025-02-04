from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Events2Posts(Base):
    __tablename__ = 'events_events2post'

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String)
    title = Column(String, nullable=False)
    full_text = Column(String, nullable=True)
    image = Column(String, nullable=True)
    price = Column(String, nullable=True)
    status = Column(String, nullable=False)
    post_url = Column(String, nullable=False)
    url = Column(String, nullable=False)
    place_id = Column(Integer, nullable=True)
    is_ready = Column(Boolean, nullable=True)
    from_date = Column(DateTime, nullable=True)
    to_date = Column(DateTime, nullable=True)
    address = Column(String, nullable=True)
    category = Column(String, nullable=True)
    main_category_id = Column(Integer, nullable=True)


class Exhibitions(Base):
    __tablename__ = 'exhibitions'

    post_id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    date_before = Column(DateTime, nullable=True)


class DsnBotEvents(Base):
    __tablename__ = 'bot_events'
    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    post_id = Column(Integer, nullable=True)
    date_from = Column(DateTime, nullable=True)
    date_to = Column(DateTime, nullable=True)
    price = Column(String, nullable=True)


class Place(Base):
    __tablename__ = 'place_place'
    id = Column(String, primary_key=True, index=True)
    place_name = Column(String)
    place_address = Column(String, nullable=False)
    place_url = Column(String, nullable=False)
    place_metro = Column(String, nullable=False)
    place_image = Column(String, nullable=False)


# class PlaceSchedule(Base):
#     __tablename__ = 'place_placeschedule'
#     id = Column(String, primary_key=True, index=True)
#     schedule_type = Column(String)
#     weekday = Column(Integer, nullable=True)
#     date = Column(Date, nullable=True)
#     open_time = Column(Time, nullable=True)
#     close_time = Column(Time, nullable=True)
#     place_id = Column(ForeignKey(Place))
