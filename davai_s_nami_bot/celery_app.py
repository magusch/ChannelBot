import os
from celery import Celery
from celery.schedules import crontab
from redis import Redis


def create_celery_app():
    celery_app = Celery(
        'davai_s_nami_bot',
        broker=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
    )

    print(f'broker:')
    print(os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'))


    celery_app.conf.update(
        result_backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
        timezone='UTC',
        beat_schedule={
            'schedule-posting-tasks': {
                'task': 'davai_s_nami_bot.celery_tasks.schedule_posting_tasks',
                'schedule': crontab(minute='*/5'),
            },
            'update-events': {
                'task': 'davai_s_nami_bot.celery_tasks.full_update',
                'schedule': crontab(hour=0, minute=0),
            },
        },
        include=['davai_s_nami_bot.celery_tasks']
    )

    return celery_app


celery_app = create_celery_app()

redis_host = os.getenv('REDIS_HOST', 'localhost')
print(redis_host)
redis_client = Redis(host=redis_host, port=6379, db=0)