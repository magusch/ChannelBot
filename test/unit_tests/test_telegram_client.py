import os
import sys
import pytest
from unittest.mock import patch, MagicMock, mock_open
import fakeredis
import json

# Создаем фейковый Redis
fake_redis = fakeredis.FakeRedis()

# Добавляем тестовые данные в Redis
test_site_params = {
    "site_id": "test_site_id",
    "site_name": "test_site_name",
    "site_url": "https://test-site.com",
    "site_token": "test_site_token",
}
fake_redis.setex(
    'parameters:dsn_site',
    3600,  # TTL в секундах
    json.dumps(test_site_params)
)

# Устанавливаем тестовые значения переменных окружения
test_env = {
    "TIMEPAD_TOKEN": "test_timepad_token",
    "BOT_TOKEN": "0000000000:test_telegram_token",
    "CHANNEL_ID": "-100123456789",
    "DEV_CHANNEL_ID": "-100987654321",
    "VK_GROUP_ID": "test_vk_group_id",
    "VK_DEV_GROUP_ID": "test_vk_dev_group_id",
    "VK_ACCESS_TOKEN": "test_vk_token",
    "OPENAI_API_KEY": "test_openai_key",
    "ANTHROPIC_API_KEY": "test_anthropic_key",
    "DSN_LOGIN": "test_login",
    "DSN_PASSWORD": "test_password",
}

for key, value in test_env.items():
    os.environ[key] = value

# Патчим Redis до импорта модулей проекта
patches = [
    patch('davai_s_nami_bot.celery_app.redis_client', fake_redis),
    patch('davai_s_nami_bot.helper.dsn_parameters.redis_client', fake_redis),
]

# Активируем патчи
for p in patches:
    p.start()

# Теперь можно импортировать модули проекта
from davai_s_nami_bot.clients import Telegram
from davai_s_nami_bot.events import Event


@pytest.fixture
def mock_telebot():
    with patch('davai_s_nami_bot.clients.TeleBot') as mock:
        mock_bot = MagicMock()
        mock.return_value = mock_bot
        yield mock_bot


@pytest.fixture
def telegram_client(mock_telebot):
    # Создаем экземпляр клиента Telegram для тестов с тестовым токеном
    return Telegram()


@pytest.fixture
def mock_event():
    # Создаем мок события для тестов
    return Event(
        event_id='test_123',
        title="🎭 Тестовое событие",
        full_text="Описание тестового события",
        price="100 ₽",
        price_int=100,
        from_date="2025-01-01",
        to_date="2025-01-02",
        image="https://ucare.timepad.ru/eaf79291-986f-4159-9c19-b15941abac42/",
        category="test_category",
        address="ул. Тестовая, 1",
        url="https://example.com/test",
        ticket_url="https://example.com/test/tickets",
        source="timepad",
        post="🎭 Тестовое событие\n\nОписание тестового события\n\n🏙 Где: ул. Тестовая, 1\n💸 Вход: 100 ₽\n\nПодробнее: https://example.com/test"
    )


def test_send_text(telegram_client, mock_telebot):
    """Тест отправки текстового сообщения"""
    # Настраиваем мок
    mock_telebot.send_message.return_value = True
    
    # Вызываем метод
    telegram_client.send_text("Test message", destination_id="test_channel")
    
    # Проверяем, что метод был вызван с правильными параметрами
    mock_telebot.send_message.assert_called_once_with(
        chat_id="test_channel",
        text="Test message",
        disable_web_page_preview=True,
        reply_markup=None,
    )


def test_send_image(telegram_client, mock_telebot):
    """Тест отправки сообщения с изображением"""
    # Настраиваем мок
    mock_telebot.send_photo.return_value = True

    # Вызываем метод
    with patch("builtins.open", mock_open(read_data=b"fake-image-bytes")):
        telegram_client.send_image(
            text="Test message with image",
            image_path="test_image.jpg",
            destination_id="test_channel"
        )

    # Проверяем, что метод был вызван с правильными параметрами
    mock_telebot.send_photo.assert_called_once()
    call_args = mock_telebot.send_photo.call_args
    assert call_args[1]["chat_id"] == "test_channel"
    assert call_args[1]["caption"] == "Test message with image"


def test_send_post(telegram_client, mock_telebot, mock_event):
    """Тест отправки поста события"""
    # Настраиваем мок
    mock_telebot.send_photo.return_value = MagicMock(message_id=12345)

    with patch("builtins.open", mock_open(read_data=b"fake-image-bytes")), \
         patch("davai_s_nami_bot.crud.add_posted_event_to_dsn_bot"), \
         patch("davai_s_nami_bot.crud.set_post_url"), \
         patch("davai_s_nami_bot.crud.add_exhibition_to_dsn_bot"):
        telegram_client.send_post(
            event=mock_event,
            image_path="test_image.jpg",
            environ="dev"
        )

    # Проверяем, что метод был вызван с правильными параметрами
    mock_telebot.send_photo.assert_called_once()
    call_args = mock_telebot.send_photo.call_args
    assert call_args[1]["chat_id"] == os.environ.get("DEV_CHANNEL_ID")
    assert call_args[1]["caption"] == mock_event.post


def test_send_post_without_image(telegram_client, mock_telebot, mock_event):
    """Тест отправки поста события без изображения"""
    # Настраиваем мок
    mock_telebot.send_message.return_value = MagicMock(message_id=12345)

    with patch("davai_s_nami_bot.crud.add_posted_event_to_dsn_bot"), \
         patch("davai_s_nami_bot.crud.set_post_url"), \
         patch("davai_s_nami_bot.crud.add_exhibition_to_dsn_bot"):
        telegram_client.send_post(
            event=mock_event,
            image_path=None,
            environ="dev"
        )

    # Проверяем, что метод был вызван с правильными параметрами
    mock_telebot.send_message.assert_called_once()
    call_args = mock_telebot.send_message.call_args
    assert call_args[1]["chat_id"] == os.environ.get("DEV_CHANNEL_ID")
    assert call_args[1]["text"] == mock_event.post
    assert call_args[1]["disable_web_page_preview"] == True