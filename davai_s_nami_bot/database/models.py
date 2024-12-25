from sqlalchemy import Column, Integer, String, DateTime
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
    # is_ready = Column(Boolean, nullable=True)
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