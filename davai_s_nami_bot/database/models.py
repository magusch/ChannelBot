from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Events2Posts(Base):
    __tablename__ = 'events_events2post'

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String)
    title = Column(String, nullable=False)
    price = Column(String, nullable=True)
    status = Column(String, nullable=False)
    post_url = Column(String, nullable=False)
    from_date = Column(DateTime, nullable=True)
    to_date = Column(DateTime, nullable=True)