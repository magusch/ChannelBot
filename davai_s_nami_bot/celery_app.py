import os
from celery import Celery
from celery.schedules import crontab
from redis import Redis

from .settings.settings_loader import settings


def create_celery_app():
    celery_app = Celery(
        'davai_s_nami_bot',
        broker=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
        broker_connection_retry_on_startup=True,
    )

    beat_schedules = {
        'update-events': {
            'task': 'davai_s_nami_bot.celery_tasks.full_update',
            'schedule': crontab(hour=0, minute=0),
        },
        'process-reminders': {
            'task': 'davai_s_nami_bot.celery_tasks.process_reminders',
            'schedule': crontab(minute='*/30'),
        },
        'update-adaptive-scoring': {
            'task': 'davai_s_nami_bot.celery_tasks.update_adaptive_scoring',
            'schedule': crontab(day_of_week=0, hour=3, minute=0),  # Monday 3 AM
        },
    }

    if settings.prepare_events_limit > 0:
        beat_schedules['prepare-unprepared-events'] = {
            'task': 'davai_s_nami_bot.celery_tasks.prepare_unprepared_events',
            'schedule': crontab(minute=0, hour=1),
            'kwargs': {'limit': settings.prepare_events_limit},
        }

    if settings.task_event_post:
        beat_schedules['schedule-posting-tasks'] = {
            'task': 'davai_s_nami_bot.celery_tasks.schedule_posting_tasks',
            'schedule': crontab(minute='*/5')
        }
    elif settings.task_digest_post:
        beat_schedules['schedule-generated-posting-tasks'] = {
            'task': 'davai_s_nami_bot.celery_tasks.schedule_generated_posting_tasks',
            'schedule': crontab(minute='*/30')
        }

    celery_app.conf.update(
        result_backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
        timezone=settings.timezone if settings.timezone else ['UTC'],
        enable_utc=True,
        beat_schedule=beat_schedules,
        include=['davai_s_nami_bot.celery_tasks'],
        task_soft_time_limit=600,
        task_time_limit=1200,
    )

    return celery_app


celery_app = create_celery_app()

redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_client = Redis(host=redis_host, port=6379, db=0)