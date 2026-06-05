# import os
# import pytest
# import fakeredis

from celery.result import AsyncResult
from unittest.mock import patch

from davai_s_nami_bot.celery_app import celery_app


# @pytest.fixture(scope="module")
# def mock_redis():
#     # Создаем экземпляр фейкового Redis
#     fake_redis = fakeredis.FakeRedis()
#
#     # Добавляем тестовые записи, если необходимо
#     fake_redis.set("test_key", "test_value")
#     fake_redis.set("another_key", "another_value")
#
#     # Замокаем клиент Redis
#     with patch("redis.Redis", return_value=fake_redis):
#         yield fake_redis
#
#
# @pytest.fixture(scope="module", autouse=True)
# def configure_celery(mock_redis):
#     # Подменяем все соответствующие компоненты в Celery
#     with patch("celery.backends.redis.RedisBackend", return_value=mock_redis):
#         # Устанавливаем параметры конфигурации Celery
#         celery_app.conf.update(
#             broker_url="redis://mocked-redis",  # Используем mock Redis для брокера
#             result_backend="redis://mocked-redis",  # Используем mock Redis для хранения результатов
#             task_always_eager=True,  # Задачи выполняются локально
#             task_eager_propagates=True,  # Ошибки задач пробрасываются
#         )
#         yield



def test_celery_task():
    # Тестовые данные для задачи
    data = {
        "date_from": "2025-01-01",
        "fields": ["id", "title", "price", "main_category_id"],
        "date_to": "2025-11-30",
        "limit": 10,
    }

    # Отправляем задачу в Celery
    result = celery_app.send_task(
        "davai_s_nami_bot.celery_tasks.get_posted_events",
        args=[data],
    )

    # Проверяем результат выполнения задачи
    task_result = AsyncResult(result.id)
    task_result.get(timeout=30)  # Ждем результата
    assert task_result.result["status"] == "success"



def test_refactor_post_with_openai():
    # Тестовые данные для задачи
    event_data = {
        "id": 456,
        "title": "Мастер-класс по живописи",
        "text": "Приглашаем на увлекательный мастер-класс по живописи маслом. Вы научитесь основам работы с масляными красками и создадите свою первую картину под руководством опытного художника. Все материалы предоставляются. Мероприятие пройдет в субботу в 15:00 в студии 'Палитра'.",
        "price": "1500 рублей",
        "address": "Студия 'Палитра', ул. Художников, 15, м. Чернышевская",
        "url": "https://example.com/event/456"
    }

    # Мокаем OpenAI клиент
    with patch('openai.OpenAI') as mock_openai:
        # Настраиваем мок для возврата предопределенного ответа
        mock_client = mock_openai.return_value
        mock_completion = mock_client.chat.completions.create.return_value
        mock_completion.choices = [
            type('obj', (object,), {
                'message': type('obj', (object,), {
                    'content': """
                    заголовок => 🎨 Мастер-класс «Живопись маслом»;
                    текст => Увлекательное погружение в мир масляной живописи, где каждый сможет создать свою первую картину под руководством опытного художника. Все необходимые материалы будут предоставлены, а уютная атмосфера студии поможет раскрыть творческий потенциал.;
                    категория => Мастер-класс;
                    адрес => Студия 'Палитра', ул. Художников, 15, м. Чернышевская;
                    стоимость => 1500 ₽;
                    ссылка => https://example.com/event/456;
                    """
                })
            })
        ]

        # Отправляем задачу в Celery
        result = celery_app.send_task(
            "davai_s_nami_bot.celery_tasks.refactor_post_with_openai",
            args=[event_data],
        )

        # Проверяем результат выполнения задачи
        task_result = AsyncResult(result.id)
        task_result.get(timeout=30)  # Ждем результата
        assert task_result.result["status"] == "success"
        assert "title" in task_result.result["data"]
        assert "prepared_text" in task_result.result["data"]



def test_post_to_telegram_with_mock():
    event_data = {
        "id": 789,
        "title": "🎵 Концерт «Классика в современности»",
        "prepared_text": "Уникальное музыкальное событие, где классические произведения исполняются в современной обработке. Талантливые музыканты представят новый взгляд на бессмертные шедевры.",
        "category": "Концерт",
        "address": "Концертный зал 'Гармония', пр. Музыкальный, 30, м. Площадь Искусств",
        "price": "500 ₽",
        "url": "https://example.com/event/789"
    }

    # Мокаем телеграм бота
    with patch('telebot.TeleBot') as mock_telebot:
        # Настраиваем мок для имитации успешной отправки сообщения
        mock_bot = mock_telebot.return_value
        mock_bot.send_message.return_value = True
        
        # Мокаем DSNParameters для возврата тестового канала
        with patch('davai_s_nami_bot.helper.dsn_parameters.DSNParameters') as mock_params:
            mock_params_instance = mock_params.return_value
            mock_params_instance.site_parameters.return_value = "test_channel_id"
            
            # Отправляем задачу в Celery
            result = celery_app.send_task(
                "davai_s_nami_bot.celery_tasks.post_to_telegram",
                args=[event_data],
            )

            # Проверяем результат выполнения задачи
            task_result = AsyncResult(result.id)
            task_result.get(timeout=30)  # Ждем результата
            assert task_result.result["status"] == "success"
            
            # Проверяем, что метод отправки сообщения был вызван с правильными параметрами
            mock_bot.send_message.assert_called_once()
            args, kwargs = mock_bot.send_message.call_args
            assert "test_channel_id" in args or kwargs.get("chat_id") == "test_channel_id"



# def test_post_to_telegram():
#     # Тестовые данные для задачи
#     event_data = {
#         "id": 123,
#         "title": "🎭 Выставка «Современное искусство»",
#         "prepared_text": "Увлекательная выставка современного искусства, представляющая работы молодых художников. Посетители смогут увидеть необычные инсталляции и познакомиться с новыми тенденциями в искусстве.",
#         "category": "Выставка",
#         "address": "Галерея современного искусства, ул. Примерная, 42, м. Невский проспект",
#         "price": "300 ₽",
#         "url": "https://example.com/event/123"
#     }

#     # Отправляем задачу в Celery
#     result = celery_app.send_task(
#         "davai_s_nami_bot.celery_tasks.post_to_telegram",
#         args=[event_data],
#     )

#     # Проверяем результат выполнения задачи
#     task_result = AsyncResult(result.id)
#     task_result.get(timeout=30)  # Ждем результата
#     assert task_result.result["status"] == "success"


def test_get_events_from_timepad():
    # Тестовые данные для задачи
    data = {
        "date_from": "2025-01-01",
        "date_to": "2025-01-31",
        "limit": 5,
        "city": "spb"
    }

    # Отправляем задачу в Celery
    result = celery_app.send_task(
        "davai_s_nami_bot.celery_tasks.get_events_from_timepad",
        args=[data],
    )

    # Проверяем результат выполнения задачи
    task_result = AsyncResult(result.id)
    task_result.get(timeout=30)  # Ждем результата
    assert task_result.result["status"] == "success"


def test_get_events_from_vk():
    # Тестовые данные для задачи
    data = {
        "date_from": "2025-01-01",
        "date_to": "2025-01-31",
        "limit": 5,
        "city": "spb"
    }

    # Отправляем задачу в Celery
    result = celery_app.send_task(
        "davai_s_nami_bot.celery_tasks.get_events_from_vk",
        args=[data],
    )

    # Проверяем результат выполнения задачи
    task_result = AsyncResult(result.id)
    task_result.get(timeout=30)  # Ждем результата
    assert task_result.result["status"] == "success"


def test_refactor_event_with_claude():
    # Тестовые данные для задачи
    event_data = {
        "id": 789,
        "title": "Концерт классической музыки",
        "text": "Приглашаем на концерт классической музыки в исполнении симфонического оркестра. В программе произведения Моцарта, Бетховена и Чайковского. Концерт состоится в Большом зале филармонии в 19:00. Стоимость билетов от 800 рублей.",
        "price": "от 800 рублей",
        "category": "Концерт",
        "address": "Большой зал филармонии, ул. Михайловская, 2",
        "url": "https://example.com/event/789"
    }

    # Отправляем задачу в Celery
    result = celery_app.send_task(
        "davai_s_nami_bot.celery_tasks.refactor_event_with_claude",
        args=[event_data],
    )

    # Проверяем результат выполнения задачи
    task_result = AsyncResult(result.id)
    task_result.get(timeout=30)  # Ждем результата
    assert task_result.result["status"] == "success"


def test_save_event_to_database():
    # Тестовые данные для задачи
    event_data = {
        "id": "TEST123",
        "title": "Тестовое мероприятие",
        "text": "Описание тестового мероприятия для проверки сохранения в базу данных",
        "price": "Бесплатно",
        "category": "Тест",
        "address": "Тестовый адрес, 123",
        "url": "https://example.com/test123",
        "image": "https://example.com/test123.jpg",
        "from_date": "2025-01-15T18:00:00",
        "to_date": "2025-01-15T20:00:00"
    }

    # Отправляем задачу в Celery
    result = celery_app.send_task(
        "davai_s_nami_bot.celery_tasks.save_event_to_database",
        args=[event_data],
    )

    # Проверяем результат выполнения задачи
    task_result = AsyncResult(result.id)
    task_result.get(timeout=30)  # Ждем результата
    assert task_result.result["status"] == "success"


def test_get_events_from_database():
    # Тестовые данные для задачи
    data = {
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
        "limit": 10,
        "offset": 0
    }

    # Отправляем задачу в Celery
    result = celery_app.send_task(
        "davai_s_nami_bot.celery_tasks.get_events_from_database",
        args=[data],
    )

    # Проверяем результат выполнения задачи
    task_result = AsyncResult(result.id)
    task_result.get(timeout=30)  # Ждем результата
    assert task_result.result["status"] == "success"


@patch('telebot.TeleBot')
def test_post_to_vk(mock_vk):
    # Тестовые данные для задачи
    event_data = {
        "id": 321,
        "title": "Мастер-класс по фотографии",
        "prepared_text": "Приглашаем на мастер-класс по фотографии от профессионального фотографа. Вы узнаете о композиции, работе со светом и обработке фотографий.",
        "category": "Мастер-класс",
        "address": "Фотостудия 'Объектив', пр. Ленина, 15",
        "price": "1200 ₽",
        "url": "https://example.com/event/321",
        "image": "https://example.com/images/photo_workshop.jpg"
    }

    # Отправляем задачу в Celery
    result = celery_app.send_task(
        "davai_s_nami_bot.celery_tasks.post_to_vk",
        args=[event_data],
    )

    # Проверяем результат выполнения задачи
    task_result = AsyncResult(result.id)
    task_result.get(timeout=30)  # Ждем результата
    assert task_result.result["status"] == "success"


def test_post_to_site():
    # Тестовые данные для задачи
    event_data = {
        "id": 654,
        "title": "Лекция по астрономии",
        "prepared_text": "Увлекательная лекция о звездах, планетах и космических явлениях. Лектор расскажет о последних открытиях в области астрономии и ответит на вопросы слушателей.",
        "category": "Лекция",
        "address": "Планетарий, пр. Космонавтов, 22",
        "price": "500 ₽",
        "url": "https://example.com/event/654",
        "image": "https://example.com/images/astronomy_lecture.jpg",
        "from_date": "2025-02-15T19:00:00",
        "to_date": "2025-02-15T21:00:00"
    }

    # Отправляем задачу в Celery
    result = celery_app.send_task(
        "davai_s_nami_bot.celery_tasks.post_to_site",
        args=[event_data],
    )

    # Проверяем результат выполнения задачи
    task_result = AsyncResult(result.id)
    task_result.get(timeout=30)  # Ждем результата
    assert task_result.result["status"] == "success"


def test_process_event_pipeline():
    # Тестовые данные для задачи
    event_data = {
        "id": "PIPELINE987",
        "title": "Фестиваль уличной еды",
        "text": "Большой фестиваль уличной еды с участием лучших шеф-поваров города. Гости смогут попробовать блюда разных кухонь мира, посетить мастер-классы и насладиться живой музыкой.",
        "price": "Вход свободный",
        "category": "Фестиваль",
        "address": "Центральный парк, главная площадь",
        "url": "https://example.com/food-festival",
        "image": "https://example.com/images/food_fest.jpg",
        "from_date": "2025-06-10T12:00:00",
        "to_date": "2025-06-10T22:00:00"
    }

    # Отправляем задачу в Celery
    result = celery_app.send_task(
        "davai_s_nami_bot.celery_tasks.process_event_pipeline",
        args=[event_data],
    )

    # Проверяем результат выполнения задачи
    task_result = AsyncResult(result.id)
    task_result.get(timeout=60)  # Ждем результата дольше, т.к. это пайплайн
    assert task_result.result["status"] == "success"
