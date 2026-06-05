from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, ForeignKey, UniqueConstraint, SmallInteger, Time
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

EMBEDDING_DIMENSIONS = 1536

from datetime import datetime, timezone


def _utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)

Base = declarative_base()

WEEKDAY_NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вск']


class Category(Base):
    __tablename__ = 'category_category'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    name_local = Column(String(100), nullable=True)


class SubCategory(Base):
    __tablename__ = 'category_subcategory'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(250), unique=True, nullable=False)
    category_id = Column(Integer, ForeignKey('category_category.id', ondelete='SET NULL'), nullable=True)
    category = relationship("Category")


class Place(Base):
    __tablename__ = 'place_place'
    id = Column(Integer, primary_key=True, index=True)
    place_name = Column(String)
    place_address = Column(String, nullable=False)
    place_url = Column(String, nullable=False)
    place_metro = Column(String, nullable=False)
    place_image = Column(String, nullable=False)
    place_city = Column(String, nullable=True)
    # Forced category for every event scraped at this place. Overrides the
    # scraper's guessed category (e.g. a standup club tagged 'Стэндап' fixes
    # shows that escraper labels 'Концерты'). Empty/NULL = no override.
    category = Column(String(500), nullable=True)
    events = relationship("Events2Posts", back_populates="place")
    keywords = relationship("PlaceKeyword", back_populates="place")
    schedules = relationship("PlaceSchedule", back_populates="place")

    def get_schedule_str(self):
        schedules = sorted(
            [s for s in self.schedules if s.weekday is not None],
            key=lambda s: s.weekday,
        )
        if not schedules:
            return None

        # Group days with similar hours
        time_to_days = {}
        for schedule in schedules:
            key = f"{schedule.open_time.strftime('%H:%M')}-{schedule.close_time.strftime('%H:%M')}"
            time_to_days.setdefault(key, []).append(schedule.weekday)

        result = []
        for time_string, days in time_to_days.items():
            groups = []
            start = days[0]
            end = days[0]
            for day in days[1:]:
                if day == end + 1:
                    end = day
                else:
                    groups.append((start, end))
                    start = end = day
            groups.append((start, end))

            parts = []
            for start, end in groups:
                if start == end:
                    parts.append(WEEKDAY_NAMES[start])
                else:
                    parts.append(f"{WEEKDAY_NAMES[start]}-{WEEKDAY_NAMES[end]}")

            result.append(f"{', '.join(parts)} {time_string}")

        return "\n".join(result)

    def __str__(self):
        return f"{self.place_name}, {self.place_address}"


class PlaceSchedule(Base):
    __tablename__ = 'place_placeschedule'

    id = Column(Integer, primary_key=True, index=True)
    place_id = Column(Integer, ForeignKey('place_place.id'), nullable=False)
    schedule_type = Column(String(10), nullable=False, default='std')
    weekday = Column(SmallInteger, nullable=True)
    date = Column(DateTime, nullable=True)
    open_time = Column(Time, nullable=True)
    close_time = Column(Time, nullable=True)

    place = relationship("Place", back_populates="schedules")


class PlaceKeyword(Base):
    __tablename__ = 'place_placekeyword'

    id = Column(Integer, primary_key=True, index=True)
    place_id = Column(Integer, ForeignKey('place_place.id'), nullable=False)
    place_keyword = Column(String(200), nullable=False)

    place = relationship("Place", back_populates="keywords")

    def __repr__(self):
        return f"<PlaceKeyword keyword={self.place_keyword!r} place_id={self.place_id}>"


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
    image_upload = Column(String, nullable=True)
    to_date = Column(DateTime, nullable=True)
    address = Column(String, nullable=True)
    category = Column(String, nullable=True)
    source = Column(String, nullable=False)
    main_category_id = Column(Integer, nullable=True)
    score = Column(Integer, nullable=True)
    score_breakdown = Column(JSONB, nullable=True)

    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    embedding_model = Column(String(64), nullable=True)
    embedding_updated_at = Column(DateTime, nullable=True)

    bot_user_events = relationship("DsnBotUserEvents", back_populates="event", cascade="all, delete-orphan")
    dsn_user_events = relationship("DsnUserEvent", back_populates="event", cascade="all, delete-orphan")


class EventsNotApproved(Base):
    """
    Входящие мероприятия на модерацию.

    status values:
        - 'new': Новое, не обработано
        - 'extracted': AI извлёк мероприятие → создано в Events2Posts
        - 'not_event': AI определил: не мероприятие
        - 'pending': Ожидает ручной модерации
        - 'approved': Модератор одобрил → перенесено в Events2Posts
        - 'rejected': Модератор отклонил
        - 'spam': Спам/реклама
        - 'duplicate': Дубликат существующего
    """
    __tablename__ = 'events_eventsnotapprovednew'

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String)
    approved = Column(Boolean, nullable=True)  # deprecated, use status
    status = Column(String, nullable=True, default='new')
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
    place_id = Column(Integer, ForeignKey('place_place.id'), nullable=True)
    place = relationship("Place")
    score = Column(Integer, nullable=True)
    score_breakdown = Column(JSONB, nullable=True)

    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    embedding_model = Column(String(64), nullable=True)
    embedding_updated_at = Column(DateTime, nullable=True)


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
    id = Column(Integer, primary_key=True)
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
    id = Column(Integer, primary_key=True)
    ip = Column(String, nullable=False)
    endpoint = Column(String, nullable=False)
    method = Column(String, nullable=False)
    status_code = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    user_agent = Column(String, nullable=True)
    request_data = Column(String, nullable=True)

# AUTH models

class DsnUser(Base):
    __tablename__ = "dsn_user"

    id = Column(Integer, primary_key=True)
    nickname = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    telegram_nickname = Column(String, nullable=True) # TODO: delete it
    telegram_id = Column(Integer, nullable=True, index=True)
    balance = Column(Integer, default=100, nullable=True)
    weekend_guide = Column(Boolean, default=False, nullable=True)

    full_name = Column(String, nullable=True)

    dsn_user_events = relationship("DsnUserEvent", back_populates="user")

    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow_naive)
    updated_at = Column(DateTime, default=_utcnow_naive, onupdate=_utcnow_naive)


class DsnUserEvent(Base):
    __tablename__ = 'dsn_user_event'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('dsn_user.id'), index=True)
    event_id = Column(Integer, ForeignKey('events_events2post.id'), index=True)
    remind_datetime = Column(DateTime, nullable=True)
    remind_sent = Column(Boolean, nullable=True)

    user = relationship("DsnUser", back_populates="dsn_user_events")
    event = relationship("Events2Posts", back_populates="dsn_user_events")

    __table_args__ = (
        UniqueConstraint('user_id', 'event_id', name='uq_user_event'),
    )