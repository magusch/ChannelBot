import datetime, json, os, traceback
import pytz
import requests
from bs4 import BeautifulSoup
from anthropic import APIStatusError as AnthropicAPIStatusError
from openai import OpenAIError

from davai_s_nami_bot.celery_app import celery_app, redis_client
from celery import chain, chord
from celery.signals import task_postrun, task_prerun

from datetime import datetime, timedelta, timezone

from .pydantic_models import EventRequestParameters, PlaceRequestParameters

from . import crud
from . import clients
from . import events_new as events
from . import utils
from . import dsn_site
from . import dsn_site_session
from .datetime_utils import get_msk_today, STRFTIME
from .logger import get_logger, LOG_FILE, log_task

from .helper.ai_helper import AIHelper

# from .helper.open_ai_event_moderator import OpenAIEventModerator as EventModerator
# from .helper.claude_event_moderator import ClaudeEventModerator as EventModerator
# from .helper.ai.perplexity_event_moderator import PerplexityEventModerator as EventModerator
from .helper.ai.gemini_event_moderator import GeminiEventModerator as EventModerator
from .helper.ai.query_analyzer import QueryAnalyzer
from .helper.ai.raw_text_event_extractor import RawTextEventExtractor
from .helper.dsn_parameters import DSNParameters, fetch_and_store_parameters
from .helper.embeddings import (
    EmbeddingClient,
    build_embedding_input,
    current_embedding_model_label,
)

from .content_generator.services import GeneratorPost, Posting

log = get_logger(__file__)
dev_channel = clients.DevClient()

CHANNEL_LINK = os.getenv('CHANNEL_LINK')


# --- Daily-task catch-up tracking ----------------------------------------
# Beat may miss a cron slot if the container restarts; missed firings are not
# backfilled. We mark each tracked task after it finishes (success OR failure)
# so `catch_up_daily_tasks` can re-queue only the ones that never started.

_DAILY_MARKER_PREFIX = 'dsn:daily_task:'
_DAILY_MARKER_TTL = 12 * 3600  # cleared by next morning's pipeline


def _daily_task_schedule():
    """List of (task_name, hour_msk, minute_msk, weekdays_iso_or_None, kwargs).

    Keep in sync with beat_schedules in celery_app.py.
    """
    from davai_s_nami_bot.settings.settings_loader import settings

    schedule = [
        ('davai_s_nami_bot.celery_tasks.full_update', 4, 40, None, {}),
        ('davai_s_nami_bot.celery_tasks.auto_promote_by_score',
         5, 0, None, {'min_score': 70, 'limit': 20}),
        ('davai_s_nami_bot.celery_tasks.auto_moderate_mid_score_events',
         5, 10, {1, 3, 5}, {'min_score': 40, 'max_score': 69, 'sample_size': 10}),
        ('davai_s_nami_bot.celery_tasks.embed_unembedded_events',
         5, 45, None, {'limit': 100, 'table': 'both'}),
        ('davai_s_nami_bot.celery_tasks.dedupe_channel_queue',
         5, 50, None, {}),
        ('davai_s_nami_bot.celery_tasks.distribute_event_queue',
         6, 0, None, {'protect_first': 8}),
    ]
    if (settings.auto_route_to_api or {}).get('enabled'):
        schedule.append((
            'davai_s_nami_bot.celery_tasks.auto_route_to_api',
            5, 15, None, {},
        ))
    if settings.prepare_events_limit > 0:
        schedule.append((
            'davai_s_nami_bot.celery_tasks.prepare_unprepared_events',
            5, 25, None, {'limit': settings.prepare_events_limit},
        ))
    return schedule


def _daily_marker_key(task_name: str, msk_date) -> str:
    return f'{_DAILY_MARKER_PREFIX}{task_name}:{msk_date.isoformat()}'


def _tracked_daily_task_names() -> set:
    try:
        return {row[0] for row in _daily_task_schedule()}
    except Exception:
        log.exception("Failed to build tracked daily task name set")
        return set()


@task_prerun.connect
def _mark_daily_task_started(sender=None, task_id=None, task=None, **kwargs):
    """Set marker BEFORE a tracked daily task runs.

    If the worker dies mid-task (kill -9, OOM, container restart), `task_postrun`
    never fires — but this marker survives, so catch-up will not retry the job.
    Uses NX so we don't clobber a postrun marker on out-of-order signal delivery.
    """
    if task is None or task.name not in _tracked_daily_task_names():
        return
    try:
        today = get_msk_today().date()
        redis_client.set(
            _daily_marker_key(task.name, today),
            'started',
            ex=_DAILY_MARKER_TTL,
            nx=True,
        )
    except Exception:
        log.exception(f"Failed to set daily prerun marker for {task.name}")


@task_postrun.connect
def _record_daily_task_run(sender=None, task_id=None, task=None, state=None, **kwargs):
    """Update marker after a tracked daily task finishes (success or failure).

    Overwrites the `started` marker set by `task_prerun` with the final state,
    purely for visibility — catch-up already skips on any non-empty marker.
    """
    if task is None or task.name not in _tracked_daily_task_names():
        return
    try:
        today = get_msk_today().date()
        redis_client.set(
            _daily_marker_key(task.name, today),
            state or 'ran',
            ex=_DAILY_MARKER_TTL,
        )
    except Exception:
        log.exception(f"Failed to set daily marker for {task.name}")


@celery_app.task
def post_to_telegram():
    log.info(f"Posting event")
    try:
        event = dsn_site.next_event_to_channel()
        if event is not None:
            try:
                s3_key = getattr(event, 'image_upload', None)
                image_path = utils.prepare_image(event.image, s3_key=s3_key)
                clients.Clients().send_post(event=event, image_path=image_path)
                log.info("Event was posted")
            except Exception as e:
                # Preserve exception type + full traceback: str(e) alone can be a
                # cryptic value (e.g. a bare "-241") with no way to trace the source.
                error_detail = f"{type(e).__name__}: {e!r}"
                log.error(
                    f"Failed to post event {event.event_id}: {error_detail}\n"
                    f"{traceback.format_exc()}"
                )
                crud.set_status(
                    event_id=event.event_id, status="Error", error_message=error_detail
                )
                log.info(f"Event {event.event_id} marked as Error")
        else:
            log.info("Event not found (or time was changed) or already posted")
    except BaseException as e:
        error_detail = f"{type(e).__name__}: {e!r}"
        log.error(
            f"Task post_to_telegram interrupted: {error_detail}\n"
            f"{traceback.format_exc()}"
        )
        if event is not None:
            crud.set_status(
                event_id=event.event_id, status="Error", error_message=error_detail
            )
            log.info(f"Event {event.event_id} marked as Error (timeout)")
        raise
    finally:
        redis_client.delete('posting_event')
        schedule_posting_tasks.apply_async()
        try:
            dev_channel.send_file(LOG_FILE, mode="r+b", with_remove=True)
        except Exception as e:
            log.error(f"врFailed to send log to dev channel: {e}")


@celery_app.task
def post_generated_by_schedule(schedule_id: int):
    """Post a generated post for the given schedule id to its platform."""
    log.info(f"Posting generated content for schedule_id={schedule_id}")
    posting_class = Posting(log)
    postings = posting_class.schedule_posting(schedule_id)
    platform = postings.get('platform') if postings else None
    if postings:
        client_post, destination_id = None, None
        if platform == 'telegram':
            client_post = clients.Telegram()
            destination_id = clients.Telegram.constants['prod']['destination_id']
        elif platform == 'vk':
            client_post = clients.VKRequests()
            destination_id = clients.VKRequests.constants['prod']['destination_id']
        if client_post:
            try:
                if postings['image_path']:
                    client_post.send_image(text=postings['post_text'], image_path=postings['image_path'],
                                           destination_id=destination_id)
                else:
                    client_post.send_text(text=postings['post_text'], destination_id=destination_id)
                posting_class.schedule_posted(schedule_id)
                log.info(f"Schedule {schedule_id} marked as posted successfully")
            except Exception as e:
                log.error(f"Failed to post schedule {schedule_id}: {e}")
    else:
        log.info(f"No postings generated for schedule_id={schedule_id}")
    # Clean up Redis so schedule_generated_posting_tasks can reschedule
    if platform:
        redis_client.delete(f'cg_posting_event:{platform}')



@celery_app.task
def schedule_posting_tasks():
    log.info("Scheduling posting tasks based on database entries")
    msk_today = get_msk_today()
    event_time = dsn_site.next_posting_time(msk_today)

    redis_key = 'posting_event'

    if event_time is None or event_time - msk_today > timedelta(hours=1):
        if event_time is None:
            log.info("No events for posting")
        else:
            log.info(f"Next posting at {event_time.strftime('%H:%M')}, too far ahead, skipping")
        # Revoke and clean up any stale scheduled task
        stale_info = redis_client.hgetall(redis_key)
        if stale_info:
            stale_task_id = stale_info.get(b'task_id', b'').decode('utf-8')
            if stale_task_id:
                celery_app.control.revoke(stale_task_id, terminate=False)
                log.info(f"Revoked stale task {stale_task_id}")
            redis_client.delete(redis_key)
        return
    event_time_str = event_time.strftime('%Y-%m-%d %H:%M:%S')
    current_scheduled_info = redis_client.hgetall(redis_key)

    need_schedule = False

    if current_scheduled_info:
        current_scheduled_time_str = current_scheduled_info.get(b'time', b'').decode('utf-8')
        current_task_id = current_scheduled_info.get(b'task_id', b'').decode('utf-8')

        # Check if stored task is still pending
        task_alive = False
        if current_task_id:
            task_result = celery_app.AsyncResult(current_task_id)
            task_alive = task_result.state in ('PENDING', 'RETRY')

        if not task_alive:
            log.info(
                f"Stored task {current_task_id} is no longer alive (state: {task_result.state if current_task_id else 'empty'}), rescheduling"
            )
            need_schedule = True
        else:
            current_scheduled_time = datetime.strptime(
                current_scheduled_time_str, '%Y-%m-%d %H:%M:%S'
            )
            current_scheduled_time_good = msk_today.replace(
                hour=current_scheduled_time.hour, minute=current_scheduled_time.minute,
                second=0, microsecond=0,
            )
            if abs(current_scheduled_time_good - event_time) > timedelta(minutes=4):
                log.info(f"Time changed from {current_scheduled_time_str} to {event_time_str}, rescheduling")
                need_schedule = True
            else:
                log.info(f"Task {current_task_id} still alive for {event_time_str}, skipping")
    else:
        need_schedule = True

    if need_schedule:
        # Revoke old task if exists
        if current_scheduled_info:
            current_task_id = current_scheduled_info.get(b'task_id', b'').decode('utf-8')
            if current_task_id:
                celery_app.control.revoke(current_task_id, terminate=False)

        result = post_to_telegram.apply_async((), eta=event_time)
        redis_client.hset(redis_key,
                          mapping={'time': event_time_str, 'task_id': result.id})
        log.info(f"Posting task scheduled to {event_time_str} (task_id: {result.id})")


@celery_app.task
def schedule_generated_posting_tasks():
    """Schedule per-platform generated post tasks based on PostingSchedule table."""
    log.info("Scheduling generated posting tasks based on PostingSchedule entries")
    time_posting_by_platform = Posting(log).get_next_time_posting()

    for platform, schedule in time_posting_by_platform:

        redis_key = f'cg_posting_event:{platform}'
        current_scheduled_info = redis_client.hgetall(redis_key)
        need_schedule = False

        if current_scheduled_info:
            current_scheduled_time_str = current_scheduled_info.get(b'time', b'').decode('utf-8')
            current_task_id = current_scheduled_info.get(b'task_id', b'').decode('utf-8')

            task_alive = False
            if current_task_id:
                task_result = celery_app.AsyncResult(current_task_id)
                task_alive = task_result.state in ('PENDING', 'RETRY')

            if not task_alive:
                log.info(f"Stored task {current_task_id} ({platform}) is no longer alive, rescheduling")
                need_schedule = True
            else:
                current_scheduled_time = datetime.strptime(current_scheduled_time_str, '%Y-%m-%d %H:%M:%S')
                current_scheduled_time = pytz.UTC.localize(current_scheduled_time)
                if abs(current_scheduled_time - schedule['eta_utc']) > timedelta(minutes=5):
                    log.info(f"Time changed for {platform}, rescheduling")
                    need_schedule = True
                else:
                    log.info(f"Task {current_task_id} ({platform}) still alive, skipping")
        else:
            need_schedule = True

        if need_schedule:
            if current_scheduled_info:
                current_task_id = current_scheduled_info.get(b'task_id', b'').decode('utf-8')
                if current_task_id:
                    celery_app.control.revoke(current_task_id, terminate=False)

            result = post_generated_by_schedule.apply_async((schedule['id'],), eta=schedule['eta_utc'])
            schedule_time_str = schedule['eta_utc'].strftime('%Y-%m-%d %H:%M:%S')
            redis_client.hset(redis_key,
                              mapping={'time': schedule_time_str, 'task_id': result.id, 'schedule_id': str(schedule['id'])})
            log.info(f"Generated posting task ({platform}) scheduled to {schedule_time_str}")


@celery_app.task
def work_with_expired_events():
    log.info("Start working with expired events.")
    msk_today = get_msk_today()
    expired_stats = crud.update_expired_events(msk_today + timedelta(hours=1))
    log.info(
        f"Expired ReadyToPost: to_api={expired_stats.get('to_api', 0)} "
        f"(is_ready=True → OnlyApi), expired={expired_stats.get('expired', 0)} (is_ready=False/NULL)"
    )
    crud.remove_event_from_dsn_bot(msk_today + timedelta(hours=1))
    crud.remove_old_not_approved_events(msk_today + timedelta(hours=1))
    log.info("Finished with expired events.")


@celery_app.task(soft_time_limit=1800, time_limit=1920)
def update_events():
    log.info("Start updating events.")

    msk_today = get_msk_today()
    log.info("Remove old events")
    work_with_expired_events.apply_async()

    log.info("Getting events from approved organizations for next 7 days")
    approved_events = events.from_approved_organizations(days=7)
    log.info(f"Collected {len(approved_events)} approved events.")

    _update_events(
        approved_events,
        table="events_events2post",
        msk_today=msk_today
    )

    log.info("Getting new events from other organizations for next 7 days")
    other_events = events.from_not_approved_organizations(days=7)
    log.info(f"Collected {len(other_events)} events")

    _update_events(other_events, table="events_eventsnotapprovednew", msk_today=msk_today)

    events_count = len(crud.get_events_from_all_tables())

    log.info(f"Events count in database: {events_count}")


def _update_events(events, table, msk_today):
    log.info("Checking for existing events")
    new_events = dsn_site.get_new_events(events)
    log.info(f"New events count = {len(new_events)}")

    if len(new_events) > 0:
        log.info("Updating database")
        inserted_ids = []

        if table == "events_events2post":
            inserted_ids = crud.add_events_to_post(new_events, explored_date=msk_today)
            log.info("Fill empty post time")
            answer = dsn_site_session.fill_empty_post_time()
        else:
            inserted_ids = crud.add_events(new_events, explored_date=msk_today, table=table)

        return inserted_ids


@celery_app.task(soft_time_limit=1800, time_limit=1920)
def update_event_from_sites(sites=None, days=7):
    if sites is None or sites[0] == 'all':
        sites = ['timepad', 'ticketscloud', 'radario', 'vk', 'qtickets', 'mts', 'culture', 'kassir']
    log.info("Start updating events from special sites.")
    msk_today = get_msk_today()

    for site in sites:
        if site not in events.escraper_sites:
            continue
        if not events._is_scraper_enabled(site):
            log.info(f"Scraper '{site}' is disabled in settings, skipping.")
            continue
        log.info(f"Getting new events from {site} for next {days} days")
        other_events = events._call_scraper(events.escraper_sites[site], days, site)
        log.info(f"Collected {len(other_events)} events")

        _update_events(other_events, table="events_eventsnotapprovednew", msk_today=msk_today)

    events_count = len(crud.get_events_from_all_tables())

    log.info(f"Events count in database: {events_count}")


@celery_app.task
def move_approved():
    log.info("Move approved events")
    moved_ids = crud.move_approved_to_posts()
    log.info(f"Moved {len(moved_ids)} approved events to Events2Posts: {moved_ids}")


@celery_app.task
def is_empty_check():
    log.info("Check for available events in table 3")

    not_published_count = dsn_site.not_published_count()
    text = None

    if not_published_count == 1:
        text = "Warning: posting last event."

    elif not_published_count == 0:
        text = "Warning: not found events for posting."

    if text:
        dev_channel.send_text(text)


@celery_app.task
def events_from_url(event_url=None):
    log.info("Start get post from url.")
    msk_today = get_msk_today()
    events_from_urls = []
    events_to_parse = crud.get_scrape_it_events()
    list_event_to_parse = [event.url for event in events_to_parse]

    if event_url is not None:
        list_event_to_parse.append(event_url)

    not_existed_parser_event = []

    for url in list_event_to_parse:
        event = events.from_url(url)
        if event is not None:
            events_from_urls.append(event)
        else:
            not_existed_parser_event.append(url)

    if not_existed_parser_event:
        download_event_page.apply_async([not_existed_parser_event])

    if not events_from_urls:
        log.info("Nothing from url")
        return

    list_event_id = [event.event_id for event in events_to_parse]
    if list_event_id:
        crud.delete_events2post_by_event_id(list_event_id)

    crud.add_events_to_post(events_from_urls, explored_date=msk_today)


@celery_app.task
def download_event_page(urls=[]):
    for url in urls:
        response = requests.get(url)
        if response.status_code < 300:
            body = BeautifulSoup(response.text, 'html.parser').get_text()
            event = {'full_text': body, 'url': url}
            ai_update_event.apply_async([event, 1])


@celery_app.task(
    bind=True,
    autoretry_for=(OpenAIError, AnthropicAPIStatusError),
    max_retries=3,
    retry_backoff=60,
    retry_backoff_max=600,
    rate_limit='2/m',
)
def ai_update_event(self, event={}, is_new=0):
    log.info("Start get post from url.")

    msk_today = get_msk_today()
    ai_helper = AIHelper()

    ai_event = ai_helper.new_event_data(event)
    if is_new == 1:
        ai_event['event_id'] = 'AI-' + str(datetime.today().timestamp())[0:10]
        new_event_tuple = events.Event.from_dict(ai_event)
        crud.add_events_to_post([new_event_tuple], explored_date=msk_today)
    return ai_event


@celery_app.task
def ai_moderate_events(events_for_moderation=[], example_of_good_events=[]):
    log.info(f"Start AI moderation process for {len(events_for_moderation)} events.")

    moderator = EventModerator()
    if not example_of_good_events:
        params = {
            'fields': ['title', 'url', 'price', 'address', 'place_id', 'prepared_text', 'category'],
            'limit': 10, 'page': 1
        }
        parameters = EventRequestParameters(**params).with_defaults()
        example_of_good_events = crud.get_events_by_date_and_category(parameters)

    approved_ids = moderator.moderate_events(events_for_moderation, example_of_good_events)

    return approved_ids


@celery_app.task
def ai_moderate_not_approved_events(parameters: dict):
    params = EventRequestParameters(**parameters)
    not_approved_events = crud.get_not_approved_events(params)
    if not not_approved_events:
        return {"message": "No events to moderate."}

    task = chain(
        ai_moderate_events.s(not_approved_events, []),
        update_approved_events.s()
    ).apply_async()

    return {"message": "AI moderation started.", "task_id": task.id}


@celery_app.task
def update_approved_events(event_ids):
    if event_ids:
        crud.update_not_approved_events_set_approved(event_ids)
        return {"message": f"Approved {len(event_ids)} events.", "event_ids": event_ids}
    return {"message": "No events were approved."}


@celery_app.task
def full_update():
    update_parameters.apply_async()
    is_empty_check.apply_async()
    move_approved.apply_async()
    events_from_url.apply_async()
    update_events.apply_async()

    dev_channel.send_file(LOG_FILE, mode="r+b", with_remove=True)

    next_time = dsn_site.next_task_time(
        msk_today=get_msk_today(replace_seconds=True)
    )

    msg = "Next scheduled time in {time}".format(
        time=next_time.strftime(STRFTIME),
    )
    try:
        dev_channel.send_text(msg)
    except Exception as e:
        log.warning(f"Failed to send dev message: {e}")


@celery_app.task(
    bind=True,
    autoretry_for=(requests.RequestException, ValueError),
    max_retries=3, retry_backoff=30, retry_backoff_max=300,
)
def update_parameters(self, parameters={}):
    """Refresh AI prompts and other DSN parameters from Django into Redis.



    Parsing, TTL and the Redis write live in
    ``dsn_parameters.fetch_and_store_parameters`` so the reactive synchronous
    refresh in ``DSNParameters.read_param`` shares exactly the same logic.
    """
    fetch_and_store_parameters(parameters)


@celery_app.task
def prepare_events(parameters: dict):
    params = EventRequestParameters(**parameters)
    events = crud.get_approved_events(params)

    if not events:
        return {"message": "No events to remake posts."}

    update_tasks = chord(
        (
            chain(ai_update_event.s(event), update_event.s(event['id']))
            for event in events
        ),
        remake_events.s(),
    )

    task_group = update_tasks.apply_async()
    return {"message": "AI update started.", "task_id": task_group.id}


@celery_app.task
def prepare_unprepared_events(limit: int = 15):
    """Beat task: prepare events where is_ready IS NULL (draft, not yet processed by AI).

    Selection is tiered (see ``crud.get_unprepared_events``): the ``limit`` is
    split internally — queue head → random sample of nearest by date → top score.
    """
    events = crud.get_unprepared_events(limit=limit)

    if not events:
        log.info("No unprepared events found.")
        return {"message": "No unprepared events.", "count": 0}

    log.info(
        f"Preparing {len(events)} unprepared events "
        f"(ids={[e.get('id') for e in events]})."
    )

    update_tasks = chord(
        (
            chain(ai_update_event.s(event), update_event.s(event['id']))
            for event in events
        ),
        remake_events.s(),
    )

    task_group = update_tasks.apply_async()
    return {
        "message": f"AI prepare started for {len(events)} events.",
        "task_id": task_group.id,
    }


@celery_app.task
def embed_single_event(event_id: int, table: str = "events2posts"):
    """On-demand embedding for one event (e.g. dispatched by the /similar API on a miss).

    Returns {'status': 'embedded'|'no_text'|'not_found', 'event_id': id, 'model': label}.
    Errors propagate so the Celery task ends up FAILURE and clients see it via /tasks/status.
    """
    from .database.database_orm import get_db_session
    from .database.models import Events2Posts, EventsNotApproved

    model_cls = {"events2posts": Events2Posts, "not_approved": EventsNotApproved}.get(
        table
    )
    if model_cls is None:
        raise ValueError(f"Unknown table {table!r}")

    with get_db_session() as db:
        row = db.query(model_cls).filter(model_cls.id == event_id).first()
        if row is None:
            return {"status": "not_found", "event_id": event_id}

        text = build_embedding_input(row)
        if not text:
            return {"status": "no_text", "event_id": event_id}

        client = EmbeddingClient()
        vector = client.embed_batch([text])[0]
        row.embedding = vector
        row.embedding_model = client.model_label
        row.embedding_updated_at = datetime.now()
        db.commit()

        return {"status": "embedded", "event_id": event_id, "model": client.model_label}


@celery_app.task
def embed_unembedded_events(
    limit: int = 100,
    table: str = "both",
    provider: str = None,
    min_score: int = None,
    only_future: bool = False,
):
    """Backfill / refresh embeddings for Events2Posts and EventsNotApproved.

    Picks rows where embedding IS NULL OR embedding_model != current model_label.
    Changing provider/model regenerates on the next run automatically.
    table ∈ {"both", "events2posts", "not_approved"}.
    provider: None → uses EMBEDDING_PROVIDER env var (default "gemini"), or pass "openai".
    min_score / only_future: optional filters used by auto_promote_by_score to
    embed exactly the promotion candidates before the dedup gate runs.
    """
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload

    from .database.database_orm import get_db_session
    from .database.models import Events2Posts, EventsNotApproved

    tables_map = {
        "events2posts": [Events2Posts],
        "not_approved": [EventsNotApproved],
        "both": [Events2Posts, EventsNotApproved],
    }
    if table not in tables_map:
        raise ValueError(f"Unknown table {table!r}, expected one of {list(tables_map)}")

    client = EmbeddingClient(provider=provider)
    model_label = client.model_label
    total = 0

    for model_cls in tables_map[table]:
        with get_db_session() as db:
            query = (
                db.query(model_cls)
                .options(joinedload(model_cls.place))
                .filter(
                    or_(
                        model_cls.embedding.is_(None),
                        model_cls.embedding_model != model_label,
                    )
                )
            )
            if min_score is not None:
                query = query.filter(model_cls.score >= min_score)
            if only_future:
                msk_now = datetime.now(timezone.utc) + timedelta(hours=3)
                query = query.filter(model_cls.from_date > msk_now)
            rows = query.order_by(model_cls.id.desc()).limit(limit).all()
            if not rows:
                continue

            texts = [build_embedding_input(r) for r in rows]
            # Empty input would 400 from the API. Skip those rows for this run.
            valid = [(r, t) for r, t in zip(rows, texts) if t]
            if not valid:
                log.info(
                    f"{model_cls.__tablename__}: {len(rows)} rows have empty embedding input, skipping."
                )
                continue

            vectors = client.embed_batch([t for _, t in valid])
            now = datetime.now()
            for (row, _), vector in zip(valid, vectors):
                row.embedding = vector
                row.embedding_model = model_label
                row.embedding_updated_at = now
            db.commit()
            total += len(valid)
            log.info(f"{model_cls.__tablename__}: embedded {len(valid)} rows.")

    log.info(f"embed_unembedded_events done: {total} rows (table={table}).")
    return {"embedded": total, "table": table}


@celery_app.task
def dedupe_channel_queue(dry_run: bool = False):
    """Sweep the ReadyToPost queue for embedding near-duplicates.

    Safety net behind the promote-time gate: catches duplicates from every
    inflow (approved orgs, manual adds, promote runs that predate embeddings).
    Scheduled after embed_unembedded_events so fresh rows have vectors.
    Thresholds come from settings.scoring (embedding_dedup_*).
    """
    from davai_s_nami_bot.settings.settings_loader import settings

    scoring_cfg = getattr(settings, "scoring", {}) or {}
    result = crud.dedupe_ready_queue(
        max_distance=scoring_cfg.get("embedding_dedup_max_distance", 0.08),
        lookup_days=scoring_cfg.get("embedding_dedup_lookup_days", 180),
        dry_run=dry_run,
    )
    log.info(
        f"dedupe_channel_queue: checked {result['checked']} ReadyToPost, "
        f"demoted {len(result['decisions'])} (dry_run={dry_run}): {result['decisions']}"
    )
    return result


_WEEKDAYS_RU = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]


@celery_app.task(
    bind=True,
    autoretry_for=(OpenAIError,),
    max_retries=3,
    retry_backoff=60,
    retry_backoff_max=600,
    rate_limit='2/m',
)
def semantic_event_search(self, message, limit=5, max_distance=None, history=None):
    """Natural-language event search: LLM intent → embedding → filtered vector search.

    1. QueryAnalyzer (Gemini) turns the free-text message into a semantic query
       plus hard filters (dates/categories/price), resolving relative dates
       against today's MSK date.
    2. EmbeddingClient embeds the semantic query (same provider events use).
    3. crud.search_events_by_embedding ranks publicly-valid events by cosine
       distance with those filters applied.

    rate_limit/retry mirror ai_update_event because Gemini free tier is tight.
    Result is JSON-safe (crud returns ISO date strings) for the Redis backend.
    """
    msk_now = get_msk_today()
    today = msk_now.date()

    analyzer = QueryAnalyzer(DSNParameters())
    analysis = analyzer.analyze(
        message,
        today=today,
        weekday_ru=_WEEKDAYS_RU[today.weekday()],
        history=history,
    )

    query_info = {
        "message": message,
        "semantic_query": analysis["semantic_query"],
        "filters": {
            "category_ids": analysis["category_ids"],
            "date_from": (
                analysis["date_from"].isoformat() if analysis["date_from"] else None
            ),
            "date_to": analysis["date_to"].isoformat() if analysis["date_to"] else None,
            "price_max": analysis["price_max"],
            "free_only": analysis["free_only"],
            "keywords": analysis["keywords"],
        },
    }

    if not analysis["is_event_search"]:
        log.info(f"semantic_event_search: not an event search ({message!r})")
        return {
            "status": "not_event_search",
            "query": query_info,
            "result": {"events": [], "total_count": 0, "request": {}},
        }

    vector = EmbeddingClient().embed_batch([analysis["semantic_query"]])[0]

    # Make the date range inclusive of whole days: from_date at 00:00, to_date at
    # end of day, in MSK (UTC+3). The DB columns are tz-aware UTC.
    msk_tz = timezone(timedelta(hours=3))
    date_from = (
        datetime.combine(analysis["date_from"], datetime.min.time(), tzinfo=msk_tz)
        if analysis["date_from"]
        else None
    )
    date_to = (
        datetime.combine(analysis["date_to"], datetime.max.time(), tzinfo=msk_tz)
        if analysis["date_to"]
        else None
    )

    result = crud.search_events_by_embedding(
        vector,
        current_embedding_model_label(),
        date_from=date_from,
        date_to=date_to,
        category_ids=analysis["category_ids"],
        price_max=analysis["price_max"],
        free_only=analysis["free_only"],
        limit=limit,
        max_distance=max_distance,
    )

    log.info(f"semantic_event_search: {result['total_count']} events for {message!r}")
    return {"status": "success", "query": query_info, "result": result}


@celery_app.task
def auto_promote_by_score(
    min_score: int = 70,
    limit: int = 20,
    uncategorized_min_score: int = 80,
    social_min_score: int = 80,
):
    """Move high-scoring events from NotApproved to Events2Posts."""
    # Embed promotion candidates first so the embedding dedup gate inside
    # auto_promote_high_score_events has vectors to compare (the nightly
    # embed_unembedded_events run happens later, at 05:45).
    taste_pool_min = min_score - 10
    try:
        embed_unembedded_events(
            limit=150, table="not_approved", min_score=taste_pool_min, only_future=True
        )
    except Exception as e:
        log.warning(f"Pre-promote embedding failed, gate will be partial: {e}")

    # Fold the kNN taste component into candidate scores BEFORE the threshold
    # selection: similar-to-posted events get lifted, similar-to-spam demoted,
    # novel events (no close neighbours) keep their base score untouched.
    try:
        taste_stats = crud.apply_taste_to_promote_candidates(
            pool_min_score=taste_pool_min
        )
        log.info(f"Taste rescoring before promote: {taste_stats}")
    except Exception as e:
        log.warning(f"Taste rescoring failed, promoting on base scores: {e}")

    promoted_ids = crud.auto_promote_high_score_events(
        min_score=min_score,
        limit=limit,
        uncategorized_min_score=uncategorized_min_score,
        social_min_score=social_min_score,
    )
    log.info(f"Auto-promoted {len(promoted_ids)} events with score >= {min_score}")

    if promoted_ids:
        dsn_site_session.fill_empty_post_time()
        log.info("Filled empty post times for promoted events")

        upload_event_images_to_s3.apply_async(args=[promoted_ids])
        log.info(f"Scheduled S3 image upload for {len(promoted_ids)} events")

    return {"promoted_count": len(promoted_ids), "promoted_ids": promoted_ids}


@celery_app.task
def auto_route_to_api():
    """Move low-priority ReadyToPost events off the channel into the OnlyApi status.

    Parameters are read from settings.auto_route_to_api. If the section is empty
    or enabled=False the task is not scheduled in beat; a manual call still
    runs with crud.route_events_to_api defaults.
    """
    from davai_s_nami_bot.settings.settings_loader import settings

    cfg = settings.auto_route_to_api or {}
    routed_ids = crud.route_events_to_api(
        min_score=cfg.get('min_score', 55),
        hard_min_score=cfg.get('hard_min_score', 35),
        low_category_ids=cfg.get('low_category_ids') or [],
        far_days=cfg.get('far_days', 14),
        limit=cfg.get('limit', 100),
        min_channel_queue=cfg.get('min_channel_queue', 20),
    )
    log.info(f"Auto-routed {len(routed_ids)} events to OnlyApi (cfg={cfg})")
    return {"routed_count": len(routed_ids), "routed_ids": routed_ids}


@celery_app.task
def route_unschedulable_events():
    """Route ReadyToPost events that won't fit before their to_date to OnlyApi.

    Parameters are read from settings.route_unschedulable. If the section is
    empty or enabled=False the task is not scheduled in beat; a manual call still
    runs with crud.route_unschedulable_events defaults.
    """
    from davai_s_nami_bot.settings.settings_loader import settings

    cfg = settings.route_unschedulable or {}
    routed_ids = crud.route_unschedulable_events(
        protect_first=cfg.get('protect_first', 5),
        weekday_slots=cfg.get('weekday_slots', 4),
        weekend_slots=cfg.get('weekend_slots', 3),
        min_runway_days=cfg.get('min_runway_days', 1),
        limit=cfg.get('limit', 0),
    )
    log.info(f"Routed {len(routed_ids)} unschedulable events to OnlyApi (cfg={cfg})")
    return {"routed_count": len(routed_ids), "routed_ids": routed_ids}


@celery_app.task
def distribute_event_queue(protect_first: int = 10):
    """Reorder the publication queue for content variety."""
    reordered = crud.distribute_event_queue(protect_first=protect_first)
    log.info(f"Reordered {reordered} events in posting queue")
    return {"reordered_count": reordered}


@celery_app.task
def auto_moderate_mid_score_events(
    min_score: int = 40, max_score: int = 69, sample_size: int = 10
):
    """AI moderation of a random sample of mid-score events."""
    # Auto-reject junk (score < min_score)
    rejected_count = crud.auto_reject_low_score_events(max_score=min_score - 1)
    log.info(f"Auto-rejected {rejected_count} events with score < {min_score}")

    # Random sample for AI moderation
    events = crud.get_mid_score_events_sample(
        min_score=min_score, max_score=max_score, sample_size=sample_size
    )
    if not events:
        log.info("No mid-score events for AI moderation")
        return {
            "rejected_count": rejected_count,
            "moderated_count": 0,
            "approved_ids": [],
        }

    log.info(f"Sending {len(events)} mid-score events for AI moderation")
    task = chain(
        ai_moderate_events.s(events, []),
        update_approved_events.s()
    ).apply_async()

    return {
        "rejected_count": rejected_count,
        "moderated_count": len(events),
        "task_id": task.id,
    }


@celery_app.task
def update_event(new_event_data, event_id):
    if new_event_data is None:
        return {"message": f"Skipping event {event_id}, no update data"}

    new_event_data = {k: v for k, v in new_event_data.items() if v}

    # AI relevance check — reject irrelevant events before posting
    ai_relevant = new_event_data.pop('ai_relevant', True)
    ai_reject_reason = new_event_data.pop('ai_reject_reason', None)
    if ai_relevant is False or str(ai_relevant).strip().lower() in ('нет', 'no', 'false'):
        log.info(f"Event {event_id} rejected by AI: {ai_reject_reason}")
        crud.reject_event_by_ai(event_id, reason=ai_reject_reason)
        return {"message": f"Event {event_id} rejected by AI", "reason": ai_reject_reason}

    if new_event_data.get('prepared_text'):
        new_event_data['is_ready'] = True
        if crud.update_approved_event(event_id, new_event_data):
            crud.remake_event_post(event_id, save=True)
            return {**new_event_data, "event_id": event_id}

    return {"message": f"Skipping event {event_id}, no update data"}


@celery_app.task
def remake_events(events):
    # Post regeneration now happens locally inside update_event via
    # crud.remake_event_post; this chord callback only collects the ids.
    event_ids = [
        event.get('id') or event.get('event_id')
        for event in events
        if event.get('id') or event.get('event_id')
    ]
    return {"remade_ids": event_ids, "count": len(event_ids)}


@celery_app.task
def get_posted_events(parameters: dict):
    params = EventRequestParameters(**parameters).with_defaults()

    events = crud.get_events_by_date_and_category(params)
    result = {'request': parameters, 'events': events}
    return result


@celery_app.task
def get_places(parameters: dict):
    params = PlaceRequestParameters(**parameters)

    places = crud.get_places(params)
    result = {
        'request': parameters,
        'places': places
    }
    return result


@celery_app.task
def get_exhibitions_celery(parameters={}):
    exhibs = crud.get_exhibitions()

    return exhibs


@celery_app.task
def log_api_request(request_info: dict):
    """
    Log API request information to the database.
    
    Parameters
    ----------
    request_info : dict
        Dictionary containing information about the API request:
        - ip: str - IP address of the requester
        - endpoint: str - API endpoint that was accessed
        - method: str - HTTP method used (GET, POST, etc.)
        - status_code: int - HTTP status code of the response
        - timestamp: str - Time when the request was made
        - user_agent: str - User agent of the requester (optional)
        - request_data: dict - Request data/parameters (optional)
    """
    log.info(f"Logging API request from {request_info.get('ip')} to {request_info.get('endpoint')}")
    
    try:
        # Save request info to database using CRUD operations
        crud.save_api_request_log(request_info)
        log.info("API request log saved successfully")
    except Exception as e:
        log.error(f"Error saving API request log: {e}")


@celery_app.task
def send_message_to_telegram(message: str, chat_id: int):
    """
    Send a message to a specific Telegram chat.

    Parameters
    ----------
    message : str
        The message to be sent.
    chat_id : int
        The ID of the Telegram chat where the message will be sent.
    """
    try:
        clients.Telegram().send_text(text=message, destination_id=chat_id)
        log.info(f"Message sent to chat {chat_id}: {message}")
    except Exception as e:
        log.error(f"Failed to send message to chat {chat_id}: {e}")


@celery_app.task
def event_reminder():
    reminders = crud.event_reminder()
    for reminder in reminders:
        post_url = reminder['post_url']
        text_message = f"Reminder Event: [{reminder['title']}]({post_url}) is happening soon. Don't miss it!"
        remind_datetime = reminder['remind_datetime']

        send_message_to_telegram.apply_async(
            args=[text_message, reminder['telegram_id']], eta=remind_datetime
        )


@celery_app.task
def process_reminders():
    reminders = crud.get_pending_reminders()
    for reminder in reminders:
        try:
            post_url = reminder['post_url']
            text_message = f"Reminder Event: [{reminder['title']}]({post_url}) is happening soon. Don't miss it!"
            send_message_to_telegram.delay(text_message, reminder['telegram_id'])
            crud.mark_reminder_sent(reminder['id'])
        except Exception as e:
            log.error(f"Failed to send reminder {reminder['id']}: {e}")


@celery_app.task
def content_generator_event_selection(filter_set_id: int):
    generator_post = GeneratorPost()
    event_selection = generator_post.event_selection(filter_set_id)
    return event_selection


@celery_app.task
def content_generator_generate_post(
    post_template_id: int, event_selection_id: int, generated_by_id: int
):
    generator_post = GeneratorPost()
    post = generator_post.generate_post_by_template(
        post_template_id, event_selection_id, generated_by_id
    )
    return post


@celery_app.task
def content_generator_generate_post_ai(
    event_selection_id: int = None,
    event_ids: list = None,
    post_template_id: int = None,
    title: str = None,
):
    generator_post = GeneratorPost()
    post = generator_post.generate_post_by_ai(
        event_selection_id=event_selection_id,
        event_ids=event_ids,
        post_template_id=post_template_id,
        title=title,
    )
    return post


@celery_app.task
def upload_image_to_s3(file_path: str):
    result = utils.process_image_from_url(image_url=file_path)
    return result


@celery_app.task
def upload_event_images_to_s3(event_ids: list = []):
    events = crud.get_events_missing_images(event_ids)

    for event in events:
        image_url = event.get('image', None)
        if not image_url:
            continue

        result = utils.process_image_from_url(image_url=image_url)
        crud.update_image_events(event['id'], result['url'], s3_key=result.get('key'))


# =============================================================================
# RAW TEXT EVENT EXTRACTION TASKS
# =============================================================================


@celery_app.task
def extract_events_from_text(text: str, source: str, image: str = None):
    """
    Analyze raw text and save it to EventsNotApproved (status='new').

    Parameters
    ----------
    text : str
        Raw text (HTML or plain text) to analyze.
    source : str
        Source of the text (telegram, instagram, vk, etc.).
    image : str, optional
        Image URL.

    Returns
    -------
    dict
        Result with information about the created records.
    """
    log.info(f"Extracting events from text, source={source}")

    extractor = RawTextEventExtractor()
    result = extractor.analyze_and_save(text, source, image)

    # Recalculate score for created NotApproved events
    for eid in result.get("created_ids", []):
        crud.recalculate_event_score(eid, table="events_eventsnotapprovednew")

    log.info(
        f"Extraction result: is_event={result.get('is_event')}, "
        f"events_count={result.get('events_count', 0)}, "
        f"created_ids={result.get('created_ids', [])}"
    )

    return result


@celery_app.task
def process_not_approved_event(event_id: int):
    """
    Process an event from EventsNotApproved: AI analyzes full_text,
    enriches the record (title, address, price, category) and updates status.

    The event stays in EventsNotApproved:
    - is_event=true → status='extracted' (enriched, awaiting moderation)
    - is_event=false → status='not_event'

    Parameters
    ----------
    event_id : int
        ID of the record in EventsNotApproved.

    Returns
    -------
    dict
        Processing result.
    """
    log.info(f"Processing not approved event id={event_id}")

    extractor = RawTextEventExtractor()
    result = extractor.process_not_approved_event(event_id)

    log.info(f"Processing result: {result}")
    return result


@celery_app.task
def batch_process_not_approved_events(limit: int = 50, source: str = None):
    """
    Batch processing of events from EventsNotApproved (one by one via AI).
    Takes only sources in AI_SOURCES (telegram, instagram, vk).
    Enriches data and updates status: 'extracted' / 'not_event'.

    Parameters
    ----------
    limit : int
        Maximum number of events to process.
    source : str, optional
        Filter by source.

    Returns
    -------
    dict
        Processing statistics.
    """
    log.info(f"Batch processing not approved events, limit={limit}, source={source}")

    events_data = crud.get_not_approved_events_for_processing(limit=limit, source=source)

    if not events_data:
        log.info("No events to process")
        return {"processed": 0, "success": 0, "failed": 0, "not_events": 0}

    extractor = RawTextEventExtractor()
    stats = {"processed": 0, "success": 0, "failed": 0, "not_events": 0}

    for event_data in events_data:
        result = extractor.process_not_approved_event(event_data["id"])
        stats["processed"] += 1

        if result.get("success"):
            if result.get("is_event"):
                stats["success"] += 1
            else:
                stats["not_events"] += 1
        else:
            stats["failed"] += 1

    log.info(f"Batch processing complete: {stats}")
    return stats


@celery_app.task
def analyze_text_only(text: str, source: str = "unknown"):
    """
    Analyze raw text with AI without saving to the database.
    For testing and preview purposes only.

    Parameters
    ----------
    text : str
        Text for analysis.
    source : str
        source of the text (for logging and AI context).

    Returns
    -------
    dict
        Analysis result.
    """
    log.info(f"Analyzing text only, source={source}")

    extractor = RawTextEventExtractor()
    result = extractor.analyze_text(text, source)

    return result.to_dict()


@celery_app.task
def batch_process_not_approved_events_optimized(
    limit: int = 50, source: str = None, batch_size: int = 10
):
    """
    Optimized batch processing — sends multiple texts in a single AI request.
    Saves tokens by using one system message per batch.
    Updates statuses: 'extracted' / 'not_event'.

    Parameters
    ----------
    limit : int
        Maximum number of events to process.
    source : str, optional
        Filter by source.
    batch_size : int
        Batch size for the AI request (max 10).

    Returns
    -------
    dict
        Processing statistics.
    """
    log.info(
        f"Optimized batch processing, limit={limit}, source={source}, batch_size={batch_size}"
    )

    events_data = crud.get_not_approved_events_for_processing(limit=limit, source=source)

    if not events_data:
        log.info("No events to process")
        return {"processed": 0, "success": 0, "failed": 0, "not_events": 0, "batches": 0}

    extractor = RawTextEventExtractor()
    stats = {"processed": 0, "success": 0, "failed": 0, "not_events": 0, "batches": 0}

    # Split into batches
    for i in range(0, len(events_data), batch_size):
        batch = events_data[i : i + batch_size]
        stats["batches"] += 1

        log.info(f"Processing batch {stats['batches']}, size={len(batch)}")

        # Analyze the batch in a single request
        texts_for_ai = [{"id": e["id"], "text": e["text"]} for e in batch]
        results, batch_tokens = extractor.analyze_texts_batch(
            texts_for_ai, source=source or "mixed"
        )

        # Log tokens
        if batch_tokens:
            stats["input_tokens"] = (
                stats.get("input_tokens", 0) + batch_tokens.input_tokens
            )
            stats["output_tokens"] = (
                stats.get("output_tokens", 0) + batch_tokens.output_tokens
            )
            log.info(
                f"Batch tokens: input={batch_tokens.input_tokens}, output={batch_tokens.output_tokens}"
            )

        # Save results
        status_updates = []
        for idx, result in enumerate(results):
            event_data = batch[idx]
            stats["processed"] += 1

            if result.is_event and result.events:
                # Enrich NotApproved with AI data (first event)
                try:
                    extracted = result.events[0]
                    enriched = {
                        "title": extracted.title,
                        "address": extracted.address,
                        "price": extracted.price,
                        "price_int": extracted.price_int,
                        "category": extracted.category,
                        "from_date": extractor._parse_datetime(extracted.from_date),
                        "to_date": extractor._parse_datetime(extracted.to_date),
                        "url": extracted.url,
                        "ticket_url": extracted.ticket_url,
                    }
                    status_updates.append(
                        {
                            "id": event_data["id"],
                            "status": "extracted",
                            "enriched": enriched,
                        }
                    )
                    stats["success"] += 1
                    log.info(f"Event {event_data['id']} enriched with AI data")
                except Exception as e:
                    log.error(f"Error enriching event {event_data['id']}: {e}")
                    stats["failed"] += 1
            else:
                status_updates.append({"id": event_data["id"], "status": "not_event"})
                stats["not_events"] += 1

        # Bulk update of statuses and enriched data
        if status_updates:
            crud.bulk_update_not_approved_status(status_updates)
            # Recalculate scores for enriched events
            for upd in status_updates:
                if upd["status"] == "extracted":
                    crud.recalculate_event_score(
                        upd["id"], table="events_eventsnotapprovednew"
                    )

    log.info(f"Optimized batch processing complete: {stats}")
    log.info(f"Total tokens used: input={stats.get('input_tokens', 0)}, output={stats.get('output_tokens', 0)}")
    return stats


@celery_app.task
def recalculate_scores_bulk(
    table: str = "events_eventsnotapprovednew", ids: list = None, force: bool = False
):
    """Resolve place_id (if missing) and recalculate score for events.

    - ids given              → recalculate those IDs (score always updated)
    - ids=None, force=False  → only where score IS NULL
    - ids=None, force=True   → all records in the table

    Parameters
    ----------
    table : str
        "events_events2post" or "events_eventsnotapprovednew"
    ids : list[int] | None
        Optional list of specific event IDs to process.
    force : bool
        If True and ids=None — recalculate all records, not just score IS NULL.
    """
    only_null = (ids is None) and (not force)
    log.info(f"recalculate_scores_bulk: table={table}, ids={ids}, force={force}, only_null={only_null}")
    result = crud.recalculate_scores_bulk(table=table, ids=ids, only_null=only_null)
    log.info(f"recalculate_scores_bulk done: {result}")
    return result


@celery_app.task
def update_adaptive_scoring(days: int = 30):
    """Weekly task: recalculate adaptive scoring from posted vs rejected events."""
    from davai_s_nami_bot.adaptive_scoring import (
        calculate_adaptive_config,
        save_to_redis,
    )
    from davai_s_nami_bot.settings.settings_loader import settings

    log.info(f"update_adaptive_scoring: collecting data for last {days} days")
    data = crud.get_adaptive_scoring_data(days=days)
    pos_count = len(data["positive"])
    neg_count = len(data["negative"])
    log.info(f"update_adaptive_scoring: {pos_count} positive, {neg_count} negative events")

    if pos_count < 10 or neg_count < 10:
        log.warning("Not enough data for adaptive scoring, skipping")
        return {
            "status": "skipped",
            "reason": "insufficient_data",
            "positive": pos_count,
            "negative": neg_count,
        }

    base_config = getattr(settings, "scoring", {})
    adaptive = calculate_adaptive_config(data["positive"], data["negative"], base_config)
    save_to_redis(redis_client, adaptive)

    log.info(
        f"update_adaptive_scoring done: {adaptive.get('source_scores', {})} sources, "
        f"{adaptive.get('category_scores', {})} categories"
    )
    return {
        "status": "ok",
        "positive": pos_count,
        "negative": neg_count,
        "adaptive_source_scores": adaptive.get("source_scores"),
        "adaptive_category_scores": adaptive.get("category_scores"),
        "suggested_boost": adaptive.get("suggested_boost_keywords"),
        "suggested_penalty": adaptive.get("suggested_penalty_keywords"),
    }


@celery_app.task
def catch_up_daily_tasks():
    """Safety net for missed daily beat firings (e.g. due to container restart).

    For each task in `_daily_task_schedule()` whose MSK scheduled time has
    already passed today: if no completion marker is set in Redis, queue it.
    A task that ran (success OR error) sets its marker via the `task_postrun`
    signal, so a failing job is NOT retried — operator decides.

    The Redis SET ... NX claim makes the catch-up itself idempotent: if two
    catch-up runs overlap, only the first queues the missing task.
    """
    now_msk = get_msk_today()
    today = now_msk.date()
    queued = []
    skipped = []

    for task_name, hour, minute, weekdays, task_kwargs in _daily_task_schedule():
        if weekdays is not None and now_msk.isoweekday() not in weekdays:
            continue
        scheduled = now_msk.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_msk < scheduled:
            continue

        key = _daily_marker_key(task_name, today)
        claimed = redis_client.set(key, 'catch_up_queued', ex=_DAILY_MARKER_TTL, nx=True)
        if not claimed:
            skipped.append(task_name)
            continue

        log.warning(
            f"catch_up_daily_tasks: {task_name} missed today's slot "
            f"{hour:02d}:{minute:02d} MSK, firing now (kwargs={task_kwargs})"
        )
        celery_app.send_task(task_name, kwargs=task_kwargs)
        queued.append(task_name)

    log.info(
        f"catch_up_daily_tasks done: queued={queued}, "
        f"skipped={len(skipped)} already-tracked"
    )
    return {'queued': queued, 'skipped_count': len(skipped)}
