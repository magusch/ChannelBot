import logging
import os
from celery import Celery
from celery.schedules import crontab
from celery.signals import before_task_publish, task_postrun, task_prerun
from redis import Redis

from . import city_context
from .settings.settings_loader import settings

log = logging.getLogger(__name__)


def create_celery_app():
    celery_app = Celery(
        'davai_s_nami_bot',
        broker=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
        broker_connection_retry_on_startup=True,
    )

    beat_schedules = {}
    for index, city in enumerate(settings.scheduled_cities()):
        with city_context.use_city(city):
            city_schedules = _city_beat_schedules()
        offset = settings.beat_offset_minutes(city)
        for name, entry in city_schedules.items():
            entry = dict(entry)
            entry['options'] = {**entry.get('options', {}), 'headers': {'city': city}}
            if index:
                entry['schedule'] = _shift(entry['schedule'], offset)
                name = f'{name}:{city}'
            beat_schedules[name] = entry

    celery_app.conf.update(
        result_backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
        timezone=settings.timezone if settings.timezone else ['UTC'],
        enable_utc=True,
        beat_schedule=beat_schedules,
        beat_schedule_filename='/tmp/celerybeat-schedule',
        include=['davai_s_nami_bot.celery_tasks'],
        task_soft_time_limit=600,
        task_time_limit=1200,
        task_track_started=True,
    )

    return celery_app


def _shift(schedule, offset_minutes):
    """Move a daily ``crontab(hour=H, minute=M)`` by ``offset_minutes``
    (``settings.beat_offset_minutes``).

    Only schedules with a single fixed hour and minute are shifted; frequent ones
    (every 5/30 minutes, hour ranges) already interleave and are left as is.
    """
    hours, minutes = schedule.hour, schedule.minute
    if len(hours) != 1 or len(minutes) != 1:
        return schedule
    total = next(iter(hours)) * 60 + next(iter(minutes))
    total = (total + offset_minutes) % (24 * 60)
    return crontab(
        hour=total // 60, minute=total % 60,
        day_of_week=schedule._orig_day_of_week,
        day_of_month=schedule._orig_day_of_month,
        month_of_year=schedule._orig_month_of_year,
    )


def _city_beat_schedules():
    """Beat entries of the current city (settings resolve per city)."""
    beat_schedules = {
        'update-events': {
            'task': 'davai_s_nami_bot.celery_tasks.full_update',
            'schedule': crontab(hour=4, minute=40),
        },
        'process-reminders': {
            'task': 'davai_s_nami_bot.celery_tasks.process_reminders',
            'schedule': crontab(minute='*/30'),
        },
        'update-adaptive-scoring': {
            'task': 'davai_s_nami_bot.celery_tasks.update_adaptive_scoring',
            'schedule': crontab(hour=3, minute=0),  # Daily at 3 AM
        },
    }

    # Daily pipeline (MSK), order matters:
    # 04:40 full_update         — scraping (including approved-orgs to Events2Posts)
    # 05:00 auto_promote        — NotApproved.score≥70 → Events2Posts (is_ready=NULL)
    # 05:05 route_mid_score     — evidenced NotApproved 55-69 → OnlyApi (trusted organizer / taste)
    # 05:10 auto_moderate       — MWF, auto-reject score<40 (+ AI sample of 40-69 if auto_moderate_sample_size>0)
    # 05:15 auto_route_to_api   — low scoring ReadyToPost → OnlyApi (until prepare, not spend AI tokens)
    # 05:22 dedupe_queue_early  — embedding near-dups out before AI prep is spent
    # 05:25 prepare_unprepared  — AI-prep is_ready=NULL
    # 05:45 embed_unembedded    — embedding for all
    # 05:50 dedupe_channel_queue— embedding near-dups out of ReadyToPost
    # 06:00 distribute_queue    — re-balance queue

    beat_schedules['auto-promote-by-score'] = {
        'task': 'davai_s_nami_bot.celery_tasks.auto_promote_by_score',
        'schedule': crontab(minute=0, hour=5),
        'kwargs': settings.auto_promote_kwargs(),
    }

    if settings.route_mid_score_to_api.get('enabled'):
        beat_schedules['route-mid-score-to-api'] = {
            'task': 'davai_s_nami_bot.celery_tasks.route_mid_score_to_api',
            'schedule': crontab(minute=5, hour=5),
        }

    beat_schedules['auto-moderate-mid-score'] = {
        'task': 'davai_s_nami_bot.celery_tasks.auto_moderate_mid_score_events',
        'schedule': crontab(minute=10, hour=5, day_of_week='1,3,5'),  # Mon, Wed, Fri
        'kwargs': {
            'min_score': 40,
            'max_score': 69,
            'sample_size': settings.auto_moderate_sample_size,
        },
    }

    if settings.auto_route_to_api.get('enabled'):
        beat_schedules['auto-route-to-api'] = {
            'task': 'davai_s_nami_bot.celery_tasks.auto_route_to_api',
            'schedule': crontab(minute=15, hour=5),  # after auto_promote (05:00), before prepare (05:25)
        }

    if settings.route_unschedulable.get('enabled'):
        beat_schedules['route-unschedulable-events'] = {
            'task': 'davai_s_nami_bot.celery_tasks.route_unschedulable_events',
            # after auto_route (05:15), before prepare (05:25) so we don't spend
            # AI prep on events we're about to route off the channel
            'schedule': crontab(minute=20, hour=5),
        }

    beat_schedules['dedupe-channel-queue-early'] = {
        'task': 'davai_s_nami_bot.celery_tasks.dedupe_channel_queue',
        'schedule': crontab(minute=22, hour=5),
    }

    if settings.prepare_events_limit > 0:
        beat_schedules['prepare-unprepared-events'] = {
            'task': 'davai_s_nami_bot.celery_tasks.prepare_unprepared_events',
            'schedule': crontab(minute=25, hour=5),
            'kwargs': {'limit': settings.prepare_events_limit},
        }

    beat_schedules['embed-unembedded-events'] = {
        'task': 'davai_s_nami_bot.celery_tasks.embed_unembedded_events',
        'schedule': crontab(minute=45, hour=5),
        'kwargs': {'limit': 100, 'table': 'both'},
    }

    beat_schedules['dedupe-channel-queue'] = {
        'task': 'davai_s_nami_bot.celery_tasks.dedupe_channel_queue',
        'schedule': crontab(minute=50, hour=5),
    }

    beat_schedules['distribute-event-queue'] = {
        'task': 'davai_s_nami_bot.celery_tasks.distribute_event_queue',
        'schedule': crontab(minute=0, hour=6),
        # protect_first=8 ≈ next ~2 days of posts (at ~4 posts/day):
        # leave already-scheduled slots untouched, reorder the rest.
        'kwargs': {'protect_first': 8},
    }

    if settings.features.get('prepare_api_events_limit', 0):
        beat_schedules['prepare-api-events'] = {
            'task': 'davai_s_nami_bot.celery_tasks.prepare_api_events',
            'schedule': crontab(minute=35, hour=5),
        }

    # Safety net: re-fire daily pipeline tasks that beat missed (container
    # restart, broker hiccup). Skips anything already run today (success or
    # error) via marker set in task_postrun. Cheap when nothing's missing.
    beat_schedules['catch-up-daily-tasks'] = {
        'task': 'davai_s_nami_bot.celery_tasks.catch_up_daily_tasks',
        'schedule': crontab(minute=30, hour='6-17'),
    }

    if settings.task_event_post:
        beat_schedules['schedule-posting-tasks'] = {
            'task': 'davai_s_nami_bot.celery_tasks.schedule_posting_tasks',
            'schedule': crontab(minute='*/5')
        }
    if settings.task_digest_post:
        beat_schedules['schedule-generated-posting-tasks'] = {
            'task': 'davai_s_nami_bot.celery_tasks.schedule_generated_posting_tasks',
            'schedule': crontab(minute='*/30')
        }
        beat_schedules['pin-digests'] = {
            'task': 'davai_s_nami_bot.celery_tasks.pin_digests',
            'schedule': crontab(minute=0, hour='9-21/2')
        }

    theme_cfg = settings.content_generator or {}
    if theme_cfg.get('theme_post_enabled'):
        beat_schedules['schedule-theme-post'] = {
            'task': 'davai_s_nami_bot.celery_tasks.schedule_theme_post',
            'schedule': crontab(
                minute=theme_cfg.get('theme_post_minute', 0),
                hour=theme_cfg.get('theme_post_hour', 12),
                day_of_week=theme_cfg.get('theme_post_days', '*'),
            ),
        }

    return beat_schedules


# --- City propagation ------------------------------------------------------

_city_tokens = {}


@before_task_publish.connect
def _attach_city_header(headers=None, **kwargs):
    if headers is not None and not headers.get('city'):
        headers['city'] = city_context.current_city()


def _task_city(task):
    request = getattr(task, 'request', None)
    city = getattr(request, 'city', None)
    if not city:
        city = (getattr(request, 'headers', None) or {}).get('city')
    return city


@task_prerun.connect
def _enter_task_city(task_id=None, task=None, **kwargs):
    city = _task_city(task)
    if not city:
        return
    try:
        _city_tokens[task_id] = city_context.set_city(city)
    except city_context.UnknownCity:
        log.error(f"Task {getattr(task, 'name', task)} got invalid city header {city!r}")


@task_postrun.connect
def _leave_task_city(task_id=None, **kwargs):
    token = _city_tokens.pop(task_id, None)
    if token is not None:
        city_context.reset_city(token)


celery_app = create_celery_app()

redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_client = Redis(host=redis_host, port=6379, db=0)