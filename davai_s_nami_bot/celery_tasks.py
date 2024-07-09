import datetime
from davai_s_nami_bot.celery_app import celery_app, redis_client

from datetime import datetime, timedelta

from . import clients
from . import database
from . import events
from . import utils
from . import dsn_site
from . import dsn_site_session
from .datetime_utils import get_msk_today
from .logger import get_logger


log = get_logger(__file__)
dev_channel = clients.DevClient()


@celery_app.task
def post_to_telegram():
    log.info(f"Posting event")

    event = dsn_site.next_event_to_channel()

    if event is not None:
        msk_today = get_msk_today()
        if abs(event.posting_time - msk_today) < timedelta(seconds=300):
            image_path = utils.prepare_image(event.image)
            clients.Clients().send_post(event=event, image_path=image_path)
        else:
            log.info("Time schedule for event was changed or event already posted")
    else:
        log.info("Event not found or already posted")
    schedule_posting_tasks.apply_async()


@celery_app.task
def schedule_posting_tasks():
    log.info("Scheduling posting tasks based on database entries")
    msk_today = get_msk_today()
    event_time = dsn_site.next_posting_time(msk_today)

    event_time_str = event_time.strftime('%Y-%m-%d %H:%M:%S')
    redis_key = 'posting_event'
    current_scheduled_info = redis_client.hgetall(redis_key)

    if current_scheduled_info:
        current_scheduled_time_str = current_scheduled_info.get(b'time').decode('utf-8')
        current_scheduled_time = datetime.strptime(current_scheduled_time_str, '%Y-%m-%d %H:%M:%S')
        current_scheduled_time_good = msk_today.replace(
            hour=current_scheduled_time.hour, minute=current_scheduled_time.minute, second=0, microsecond=0
        )
        current_task_id = current_scheduled_info.get(b'task_id').decode('utf-8')
        if event_time < current_scheduled_time_good:
            # Cancel old task
            if current_task_id:
                celery_app.control.revoke(current_task_id, terminate=True)

            # Schedule new task with new time
            result = post_to_telegram.apply_async((), eta=event_time)
            redis_client.hset(redis_key,
                              mapping={'time': event_time_str, 'task_id': result.id})
            log.info(f"Posting task rescheduled to {event_time_str}")
    else:
        result = post_to_telegram.apply_async((), eta=event_time)
        redis_client.hset(redis_key,
                          mapping={'time': event_time_str, 'task_id': result.id})
        log.info(f"Posting task scheduled to {event_time_str}")


@celery_app.task
def update_events():
    log.info("Start updating events.")

    msk_today = get_msk_today()
    log.info("Remove old events")
    dsn_site_session.remove_old()
    database.remove_event_from_dsn_bot(msk_today + timedelta(hours=1))

    log.info("Getting events from approved organizations for next 7 days")
    approved_events = events.from_approved_organizations(days=7)
    log.info(f"Collected {len(approved_events)} approved events.")

    inserted_ids = _update_events(
        approved_events,
        table="events_events2post",
        msk_today=msk_today
    )

    if inserted_ids is not None:
        dsn_site_session.make_post_text(inserted_ids)

    log.info("Getting new events from other organizations for next 7 days")
    other_events = events.from_not_approved_organizations(days=7)
    log.info(f"Collected {len(other_events)} events")

    _update_events(other_events, table="events_eventsnotapprovednew", msk_today=msk_today)

    events_count = sum([
        database.rows_number(table="events_eventsnotapprovednew"),
        database.rows_number(table="events_events2post"),
    ])

    log.info(f"Events count in database: {events_count}")


def _update_events(events, table, msk_today):
    dsn_site_session.create_session()

    log.info("Checking for existing events")
    new_events = dsn_site.get_new_events(events)
    log.info(f"New events count = {len(new_events)}")

    if len(new_events) > 0:
        log.info("Updating database")
        inserted_ids = database.add_events(new_events, explored_date=msk_today, table=table)

        log.info("Fill empty post time")
        answer = dsn_site_session.fill_empty_post_time()
        log.info(answer)
        return inserted_ids


@celery_app.task
def move_approved():
    log.info("Move approved events")
    dsn_site_session.move_approved()

    log.info("Fill empty post time")
    dsn_site_session.fill_empty_post_time()


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
    event_to_parse = database.get_scrape_it_events(table="events_events2post", )
    list_event_to_parse = list(event_to_parse['url'])

    if event_url is not None: list_event_to_parse.append(event_url)

    for url in list_event_to_parse:
        event = events.from_url(url)
        events_from_urls.append(event)

    if not events_from_urls:
        log.info("Nothing from url")
        return

    if list(event_to_parse['event_id']):
        database.remove_by_event_id(list(event_to_parse['event_id']))

    inserted_ids = database.add_events(events_from_urls, explored_date=msk_today, table="events_events2post")

    if inserted_ids is not None:
        dsn_site_session.make_post_text(inserted_ids)


@celery_app.task
def full_update():
    is_empty_check.apply_async()
    move_approved.apply_async()
    events_from_url.apply_async()
    update_events.apply_async()
