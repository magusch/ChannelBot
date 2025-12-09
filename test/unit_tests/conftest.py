import os
import sys
import pytest
from unittest.mock import patch
import fakeredis
import json

from datetime import datetime

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, project_root)

from test.test_config import TEST_ENV, TEST_SITE_PARAMS

fake_redis = fakeredis.FakeRedis()

fake_redis.setex(
    'parameters:dsn_site',
    3600,  # TTL в секундах
    json.dumps(TEST_SITE_PARAMS)
)

for key, value in TEST_ENV.items():
    os.environ[key] = value

patches = [
    patch('davai_s_nami_bot.celery_app.redis_client', fake_redis),
    patch('davai_s_nami_bot.helper.dsn_parameters.redis_client', fake_redis),
]

for p in patches:
    p.start()

@pytest.fixture(scope="session")
def mock_redis():
    """Fixture for fake redis"""
    return fake_redis

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from main import app
from davai_s_nami_bot.database.models import Base, DsnUser, Events2Posts
from davai_s_nami_bot.database import database_orm

TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db_session_fixture():
    test_engine = create_engine(
        TEST_DATABASE_URL, connect_args={"check_same_thread": False}
    )
    connection = test_engine.connect()
    Base.metadata.create_all(bind=connection)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False)

    db = TestingSessionLocal(bind=connection)
    db.begin_nested()


    original_session_local = database_orm.SessionLocal
    database_orm.SessionLocal = lambda: db  # Подменяем на тестовую сессию

    try:
        yield db
    finally:
        db.rollback()
        db.close()
        connection.close()
        database_orm.SessionLocal = original_session_local


@pytest.fixture()
def client(db_session_fixture):
    """
    Test client for FastAPI
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def existing_event(db_session_fixture):
    db = db_session_fixture

    event_id = 111
    event_data = {
        "id": event_id,
        "title": "Fixtured Test Event",
        "full_text": "This event exists only for testing.",
        'post': '', 'url': '', 'ticket_url': '', 'status': 'Posted',
        'from_date': datetime(2024, 12, 25, 19, 0), 'to_date': datetime(2024, 12, 26, 21, 0),
        'image': '', 'event_id': '', "price": '', 'price_int': 100,
        'category': '', 'address': '', 'source': 'test'
    }

    event = Events2Posts(**event_data)
    db.add(event)

    db.commit()

    yield event_id