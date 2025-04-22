import pytest
from unittest.mock import MagicMock
from contextlib import contextmanager

import davai_s_nami_bot.database.database_orm as db_orm
from davai_s_nami_bot import crud, utils, clients
from davai_s_nami_bot.celery_tasks import post_to_telegram
from davai_s_nami_bot.clients import Clients, BaseClient, Telegram
from davai_s_nami_bot.events import Event


@pytest.fixture
def mock_db_session(monkeypatch):
    mock_session = MagicMock()
    @contextmanager
    def fake_get_db_session():
        yield mock_session

    monkeypatch.setattr(db_orm, 'get_db_session', fake_get_db_session)
    return mock_session


@pytest.fixture
def mock_clients(monkeypatch):
    mock_client = MagicMock()
    mock_client.return_value = MagicMock(message_id=12345)

    monkeypatch.setattr(clients.Clients, 'send_post', lambda: mock_client)

    return mock_client


@pytest.fixture
def mock_telegram_super_send_post(monkeypatch):
    mock_message = MagicMock()
    mock_message.message_id = 12345

    original_base_send_post = BaseClient.send_post

    def mock_base_send_post(self, event, image_path, environ="prod"):

        return mock_message

    monkeypatch.setattr(Clients, 'send_post', mock_base_send_post)

    return mock_message


@pytest.fixture
def mock_dev_channel(monkeypatch):
    mock_channel = MagicMock()
    monkeypatch.setattr('davai_s_nami_bot.celery_tasks.dev_channel', mock_channel)
    return mock_channel


@pytest.fixture
def mock_schedule_posting_tasks(monkeypatch):
    mock_task = MagicMock()
    monkeypatch.setattr('davai_s_nami_bot.celery_tasks.schedule_posting_tasks', mock_task)
    return mock_task


@pytest.fixture
def mock_utils(monkeypatch):
    mock_prepare = MagicMock(return_value="/path/to/image.jpg")
    monkeypatch.setattr(utils, 'prepare_image', mock_prepare)
    return mock_prepare



def test_post_to_telegram_with_exhibition(mock_telegram_super_send_post, monkeypatch):
    mock_event = MagicMock()
    mock_event.event_id = "EVENT_123"
    mock_event.main_category_id = 11  # Выставка

    # Мокаем функции crud
    add_posted_mock = MagicMock()
    set_post_url_mock = MagicMock()
    add_exhibition_mock = MagicMock()

    monkeypatch.setattr(crud, 'add_posted_event_to_dsn_bot', add_posted_mock)
    monkeypatch.setattr(crud, 'set_post_url', set_post_url_mock)
    monkeypatch.setattr(crud, 'add_exhibition_to_dsn_bot', add_exhibition_mock)

    telegram = Telegram()

    monkeypatch.setattr(telegram, '_client', MagicMock())
    mock_send_image = MagicMock(return_value=MagicMock(message_id=12345))
    monkeypatch.setattr(telegram, 'send_image', mock_send_image)

    # Вызываем метод send_post
    result = telegram.send_post(mock_event, "image.jpg")

    # Проверяем, что нужные функции были вызваны
    add_posted_mock.assert_called_once_with(mock_event, 12345)
    set_post_url_mock.assert_called_once()
    add_exhibition_mock.assert_called_once_with(mock_event, 12345)


def test_post_to_telegram_no_event(mock_db_session, mock_clients, mock_dev_channel,
                                   mock_schedule_posting_tasks, mock_utils, monkeypatch):
    # Return None for crud.get_event_to_post_now
    monkeypatch.setattr(crud, 'get_event_to_post_now', lambda: None)

    # Test function
    post_to_telegram()

    mock_utils.assert_not_called()
    mock_clients.send_post.assert_not_called()

    # Schedule and logs should work
    mock_schedule_posting_tasks.apply_async.assert_called_once()
    mock_dev_channel.send_file.assert_called_once()


def test_post_to_telegram_exception_in_send_post(mock_db_session, mock_clients, mock_dev_channel,
                                                 mock_schedule_posting_tasks, mock_utils, monkeypatch):
    # Test event
    mock_event = MagicMock(spec=Event)
    mock_event.event_id = "EVENT_123"
    mock_event.image = "original_image_path.jpg"

    # crud.get_event_to_post_now -> return mock_event
    monkeypatch.setattr(crud, 'get_event_to_post_now', lambda: mock_event)

    mock_clients.send_post.side_effect = Exception("Test exception")

    with pytest.raises(Exception):
        post_to_telegram()

    mock_schedule_posting_tasks.apply_async.assert_not_called()
    mock_dev_channel.send_file.assert_not_called()