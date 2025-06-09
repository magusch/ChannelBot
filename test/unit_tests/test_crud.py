# Create a new file: unit_tests/test_crud.py
import datetime

import pytest
import os
from unittest.mock import MagicMock, Mock
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import davai_s_nami_bot.database.database_orm as db_orm
import davai_s_nami_bot.crud as crud_module
from davai_s_nami_bot.crud import get_ready_to_post_events, get_scrape_it_events, add_events_to_post
from davai_s_nami_bot import crud
from davai_s_nami_bot.database.models import Events2Posts, Base
from davai_s_nami_bot.database import models as m
from davai_s_nami_bot.events import Event

DSN_DATABASE_URL = os.getenv('DSN_DATABASE_URL')

@pytest.fixture
def mock_db_session(monkeypatch):
    mock_session = MagicMock()
    @contextmanager
    def fake_get_db_session():
        yield mock_session

    monkeypatch.setattr(db_orm, 'get_db_session', fake_get_db_session)
    return mock_session

@pytest.fixture
def test_db():
    # Create an actual SQLite in-memory database for integration tests
    engine = create_engine(DSN_DATABASE_URL)

    # Create all tables defined in your SQLAlchemy models
    Base.metadata.create_all(engine)

    # Create a session factory
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Return a session
    db = SessionLocal()

    test_events = [
        Events2Posts(
            id=1,
            title='Test Event One', status='ReadyToPost',
            post='post content 1',full_text='full text 1',
            url='url1', post_url='111',
            from_date=datetime.datetime(2025, 7, 1),
            to_date=datetime.datetime(2025, 7, 10),
            image='image1.jpg', event_id='EVENT_111', price='300₽',
            category='Лекция', address='address 1', main_category_id=1
        ),
        Events2Posts(
            id=2, title='Test Event Two',status='ReadyToPost',
            post='post content 2',full_text='full text 2',
            url='url2', post_url='111',
            from_date=datetime.datetime(2025,8,3),
            to_date=datetime.datetime(2025,8,4),
            image='image2.jpg', event_id='EVENT_222',
            price='500₽',category='Концерт', address='address 2', main_category_id=2
        ),
        Events2Posts(
            id=3, title='Test Event Three Draft', status='Spam',
            post='draft post', full_text='draft text',
            url='url3', post_url='111',
            from_date=datetime.datetime(2030,9,14),
            to_date=datetime.datetime(2030,9,17),
            image='image3.jpg', event_id='EVENT_333',
            price='Free',category='Выставка', address='address 3', main_category_id=3
        )
    ]

    # Add all events to the database
    for event in test_events:
        db.add(event)

    # Commit the changes
    db.commit()

    try:
        yield db
    finally:
        db.close()


def test_get_ready_to_post_events(test_db, monkeypatch):
    @contextmanager
    def get_test_db():
        yield test_db

    monkeypatch.setattr(db_orm, 'get_db_session', get_test_db)

    # Insert test data
    event = Events2Posts(
        id=111,
        title='Test Event',
        status='ReadyToPost',
        post='post',
        full_text='f',
        url='url',
        from_date=datetime.datetime.today(),
        to_date=datetime.datetime.today(),
        image='image',
        event_id='EVENT_333',
        price='300₽',
        category='Лекция',
        address='address'
    )
    test_db.add(event)
    test_db.commit()

    # Act: Call the function
    result = get_ready_to_post_events()

    # Assert
    assert len(result) == 3
    assert 'Test Event' in result[0].title
    assert result[0].status == 'ReadyToPost'


def test_get_scrape_it_events(test_db, monkeypatch):
    @contextmanager
    def get_test_db():
        yield test_db

    monkeypatch.setattr(db_orm, 'get_db_session', get_test_db)

    scrape_it_event = Events2Posts(
            id=333, title='Test Event Three ScrapeIt', status='Scrape',
            post='draft post', full_text='draft text',
            url='http://timepad.ru/111', post_url='-',
            from_date=datetime.datetime(2030,9,14),
            to_date=datetime.datetime(2030,9,17),
            image='image3.jpg', event_id='EVENT_333',
            price='Free',category='Концерт', address='address 3'
        )
    test_db.add(scrape_it_event)
    test_db.commit()

    result = get_scrape_it_events()

    assert len(result) > 0
    assert 'ScrapeIt' in result[0].title
    assert result[0].status == 'Scrape'


def test_add_event_to_post(test_db, monkeypatch):
    @contextmanager
    def get_test_db():
        yield test_db

    monkeypatch.setattr(db_orm, 'get_db_session', get_test_db)

    last_queue = crud.get_last_queue_value()
    queue_increase = 3

    new_test_event = {
        'id': 222, 'title': 'Test Event NEW',
        'post': 'post content 2', 'full_text': 'full text 2',
        'url': 'url2',
        'from_date': datetime.datetime(2025, 8, 3),
        'to_date': datetime.datetime(2025, 8, 4),
        'image': 'image2.jpg', 'event_id': 'NEW_TEST_EVENT_22222',
        'price': '500₽', 'category': 'Концерт', 'address': 'address 2'

    }
    new_event_tuple = Event.from_dict(new_test_event)

    inserted_ids = add_events_to_post([new_event_tuple], datetime.datetime.today(), queue_increase)

    assert len(inserted_ids) == 1

    result = get_ready_to_post_events()

    assert len(result) == 3

    result = test_db.query(Events2Posts).order_by(Events2Posts.queue.desc())
    assert result[0].title == 'Test Event NEW'
    assert result[0].queue == last_queue + queue_increase


def test_count_events(test_db, monkeypatch):
    @contextmanager
    def get_test_db():
        yield test_db

    monkeypatch.setattr(db_orm, 'get_db_session', get_test_db)
    events_count = len(crud.get_events_from_all_tables())

    assert events_count == 3


def test_get_events_positive_categories(test_db, monkeypatch):
    @contextmanager
    def get_test_db():
        yield test_db

    monkeypatch.setattr(db_orm, 'get_db_session', get_test_db)

    test_events = [
        Events2Posts(
            id=10, title='Event Cat 1', status='Posted',
            main_category_id=1, place_id=1,
            from_date=datetime.datetime(2025, 6, 1),
            to_date=datetime.datetime(2025, 6, 5),
            post='post', full_text='text', url='url1'
        ),
        Events2Posts(
            id=11, title='Event Cat 2', status='Posted',
            main_category_id=2, place_id=1,
            from_date=datetime.datetime(2025, 6, 2),
            to_date=datetime.datetime(2025, 6, 6),
            post='post', full_text='text', url='url2'
        ),
        Events2Posts(
            id=12, title='Event Cat 3', status='Posted',
            main_category_id=3, place_id=1,
            from_date=datetime.datetime(2025, 6, 3),
            to_date=datetime.datetime(2025, 6, 7),
            post='post', full_text='text', url='url3'
        )
    ]

    for event in test_events:
        test_db.add(event)
    test_db.commit()

    params = Mock()
    params.ids = None
    params.category = [1, 2]
    params.place = None
    params.date_from = datetime.datetime(2025, 6, 1)
    params.date_to = datetime.datetime(2025, 6, 10)
    params.limit = None
    params.page = None
    params.fields = None

    result = crud.get_events_by_date_and_category(params)

    assert result['total_count'] == 2
    assert len(result['events']) == 2
    assert result['request']['category'] == [1, 2]


def test_get_events_negative_categories(test_db, monkeypatch):
    @contextmanager
    def get_test_db():
        yield test_db

    monkeypatch.setattr(db_orm, 'get_db_session', get_test_db)

    test_events = [
        Events2Posts(
            id=20, title='Event Cat 1', status='Posted',
            main_category_id=1, place_id=1,
            from_date=datetime.datetime(2025, 6, 1),
            to_date=datetime.datetime(2025, 6, 5),
            post='post', full_text='text', url='url1'
        ),
        Events2Posts(
            id=21, title='Event Cat 2', status='Posted',
            main_category_id=2, place_id=1,
            from_date=datetime.datetime(2025, 6, 2),
            to_date=datetime.datetime(2025, 6, 6),
            post='post', full_text='text', url='url2'
        ),
        Events2Posts(
            id=22, title='Event Cat 3', status='Posted',
            main_category_id=3, place_id=1,
            from_date=datetime.datetime(2025, 6, 3),
            to_date=datetime.datetime(2025, 6, 7),
            post='post', full_text='text', url='url3'
        )
    ]

    for event in test_events:
        test_db.add(event)
    test_db.commit()

    params = Mock()
    params.ids = None
    params.category = [-1]
    params.place = None
    params.date_from = datetime.datetime(2025, 6, 1)
    params.date_to = datetime.datetime(2025, 6, 10)
    params.limit = None
    params.page = None
    params.fields = None

    result = crud.get_events_by_date_and_category(params)

    assert result['total_count'] == 2
    assert len(result['events']) == 2
    assert result['request']['category'] == [-1]


def test_get_events_mixed_categories(test_db, monkeypatch):
    @contextmanager
    def get_test_db():
        yield test_db

    monkeypatch.setattr(db_orm, 'get_db_session', get_test_db)

    test_events = [
        Events2Posts(
            id=30, title='Event Cat 1', status='Posted',
            main_category_id=1, place_id=1,
            from_date=datetime.datetime(2025, 6, 1),
            to_date=datetime.datetime(2025, 6, 5),
            post='post', full_text='text', url='url1'
        ),
        Events2Posts(
            id=31, title='Event Cat 2', status='Posted',
            main_category_id=2, place_id=1,
            from_date=datetime.datetime(2025, 6, 2),
            to_date=datetime.datetime(2025, 6, 6),
            post='post', full_text='text', url='url2'
        )
    ]

    for event in test_events:
        test_db.add(event)
    test_db.commit()

    params = Mock()
    params.ids = None
    params.category = [1, -2]
    params.place = None
    params.date_from = datetime.datetime(2025, 6, 1)
    params.date_to = datetime.datetime(2025, 6, 10)
    params.limit = None
    params.page = None
    params.fields = None

    result = crud.get_events_by_date_and_category(params)

    assert result['total_count'] == 1
    assert len(result['events']) == 1
    assert result['events'][0]['main_category_id'] == 1
    assert result['request']['category'] == [1, -2]


def test_get_events_no_categories(test_db, monkeypatch):
    @contextmanager
    def get_test_db():
        yield test_db

    monkeypatch.setattr(db_orm, 'get_db_session', get_test_db)

    test_events = [
        Events2Posts(
            id=40, title='Event Cat 1', status='Posted',
            main_category_id=1, place_id=1,
            from_date=datetime.datetime(2025, 6, 1),
            to_date=datetime.datetime(2025, 6, 5),
            post='post', full_text='text', url='url1'
        ),
        Events2Posts(
            id=41, title='Event Cat 2', status='Posted',
            main_category_id=2, place_id=1,
            from_date=datetime.datetime(2025, 6, 2),
            to_date=datetime.datetime(2025, 6, 6),
            post='post', full_text='text', url='url2'
        )
    ]

    for event in test_events:
        test_db.add(event)
    test_db.commit()

    params = Mock()
    params.ids = None
    params.category = None
    params.place = None
    params.date_from = datetime.datetime(2025, 6, 1)
    params.date_to = datetime.datetime(2025, 6, 10)
    params.limit = None
    params.page = None
    params.fields = None

    result = crud.get_events_by_date_and_category(params)

    assert result['total_count'] == 2
    assert len(result['events']) == 2
    assert 'category' not in result['request']


def test_get_events_with_pagination_and_fields(test_db, monkeypatch):
    @contextmanager
    def get_test_db():
        yield test_db

    monkeypatch.setattr(db_orm, 'get_db_session', get_test_db)

    test_events = [
        Events2Posts(
            id=50, title='Event 1', status='Posted',
            main_category_id=1, place_id=1,
            from_date=datetime.datetime(2025, 6, 1),
            to_date=datetime.datetime(2025, 6, 5),
            post='post', full_text='text', url='url1'
        ),
        Events2Posts(
            id=51, title='Event 2', status='Posted',
            main_category_id=1, place_id=1,
            from_date=datetime.datetime(2025, 6, 2),
            to_date=datetime.datetime(2025, 6, 6),
            post='post', full_text='text', url='url2'
        )
    ]

    for event in test_events:
        test_db.add(event)
    test_db.commit()

    params = Mock()
    params.ids = None
    params.category = [1]
    params.place = None
    params.date_from = datetime.datetime(2025, 6, 1)
    params.date_to = datetime.datetime(2025, 6, 10)
    params.limit = 1
    params.page = 1
    params.fields = ['id', 'title', 'main_category_id']

    result = crud.get_events_by_date_and_category(params)

    assert result['total_count'] == 2
    assert len(result['events']) == 1
    assert len(result['events'][0]) == 3
    assert 'id' in result['events'][0]
    assert 'title' in result['events'][0]
    assert 'main_category_id' in result['events'][0]
    assert result['request']['limit'] == 1
    assert result['request']['page'] == 1
    assert result['request']['fields'] == ['id', 'title', 'main_category_id']


