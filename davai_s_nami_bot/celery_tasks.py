import datetime, json, os
import pytz
import requests
from bs4 import BeautifulSoup
from openai import OpenAIError

from davai_s_nami_bot.celery_app import celery_app, redis_client
from celery import chain, chord

from datetime import datetime, timedelta, timezone

from .pydantic_models import EventRequestParameters, PlaceRequestParameters

from . import crud
from . import clients
from . import events
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
from .helper.ai.raw_text_event_extractor import RawTextEventExtractor

from .content_generator.services import GeneratorPost

log = get_logger(__file__)
dev_channel = clients.DevClient()

CHANNEL_LINK = os.getenv('CHANNEL_LINK')

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
                log.error(f"Failed to post event {event.event_id}: {e}")
                crud.set_status(event_id=event.event_id, status="Error", error_message=str(e))
                log.info(f"Event {event.event_id} marked as Error")
        else:
            log.info("Event not found (or time was changed) or already posted")
    except BaseException as e:
        log.error(f"Task post_to_telegram interrupted: {e}")
        if event is not None:
            crud.set_status(event_id=event.event_id, status="Error", error_message=str(e))
            log.info(f"Event {event.event_id} marked as Error (timeout)")
        raise
    finally:
        redis_client.delete('posting_event')
        schedule_posting_tasks.apply_async()
        try:
            dev_channel.send_file(LOG_FILE, mode="r+b", with_remove=True)
        except Exception as e:
            log.error(f"Failed to send log to dev channel: {e}")



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
                celery_app.control.revoke(stale_task_id, terminate=True)
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
            log.info(f"Stored task {current_task_id} is no longer alive (state: {task_result.state if current_task_id else 'empty'}), rescheduling")
            need_schedule = True
        else:
            current_scheduled_time = datetime.strptime(current_scheduled_time_str, '%Y-%m-%d %H:%M:%S')
            current_scheduled_time_good = msk_today.replace(
                hour=current_scheduled_time.hour, minute=current_scheduled_time.minute, second=0, microsecond=0
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
                celery_app.control.revoke(current_task_id, terminate=True)

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
                    celery_app.control.revoke(current_task_id, terminate=True)

            result = post_generated_by_schedule.apply_async((schedule['id'],), eta=schedule['eta_utc'])
            schedule_time_str = schedule['eta_utc'].strftime('%Y-%m-%d %H:%M:%S')
            redis_client.hset(redis_key,
                              mapping={'time': schedule_time_str, 'task_id': result.id, 'schedule_id': str(schedule['id'])})
            log.info(f"Generated posting task ({platform}) scheduled to {schedule_time_str}")


@celery_app.task
def work_with_expired_events():
    log.info("Start working with expired events.")
    msk_today = get_msk_today()
    crud.update_expired_events(msk_today + timedelta(hours=1))
    crud.remove_event_from_dsn_bot(msk_today + timedelta(hours=1))
    crud.remove_old_not_approved_events(msk_today + timedelta(hours=1))
    log.info("Finished with expired events.")


@celery_app.task
def update_events():
    log.info("Start updating events.")

    msk_today = get_msk_today()
    log.info("Remove old events")
    work_with_expired_events.apply_async()

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

@celery_app.task
def update_event_from_sites(sites=None, days=7):
    if sites is None or sites[0] == 'all':
        sites = ['timepad', 'ticketscloud', 'radario', 'vk', 'qtickets', 'mts', 'culture', 'kassir']
    log.info("Start updating events from special sites.")
    msk_today = get_msk_today()

    for site in sites:
        if site in events.escraper_sites.keys():
            log.info(f"Getting new events from {site} for next {days} days")
            other_events = events.escraper_sites[site](days)
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

    if event_url is not None: list_event_to_parse.append(event_url)

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

    inserted_ids = crud.add_events_to_post(events_from_urls, explored_date=msk_today)
    if inserted_ids is not None:
        dsn_site_session.make_post_text(inserted_ids)


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
    autoretry_for=(OpenAIError,),
    max_retries=3,
    retry_backoff=60,
    retry_backoff_max=600,
)
def ai_update_event(self, event={}, is_new=0):
    log.info("Start get post from url.")

    msk_today = get_msk_today()
    ai_helper = AIHelper()

    ai_event = ai_helper.new_event_data(event)
    if is_new == 1:
        ai_event['event_id'] = 'AI-' + str(datetime.today().timestamp())[0:10]
        new_event_tuple = events.Event.from_dict(ai_event)
        inserted_ids = crud.add_events_to_post([new_event_tuple], explored_date=msk_today)
        if inserted_ids is not None:
            dsn_site_session.make_post_text(inserted_ids)
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


@celery_app.task
def update_parameters(parameters={}):
    response_parameters = dsn_site_session.parameter_for_dsn_channel(parameters)
    dsn_parameters = {}
    for param in response_parameters.json():

        value = param["value"]

        full_value = str(param.get("full_value", "") or "").strip()
        if full_value:
            value += f"\n{full_value}"

        if param["site"] not in dsn_parameters.keys():
            dsn_parameters[param["site"]] = {
                param["parameter_name"]: [value]
            }
        elif param['parameter_name'] not in dsn_parameters[param["site"]].keys():
            dsn_parameters[param["site"]][param['parameter_name']] = [
                value
            ]
        else:
            dsn_parameters[param["site"]][param['parameter_name']].append(param["value"])


    for site, params in dsn_parameters.items():
        redis_client.setex(f'parameters:{site}', 36000, json.dumps(params))


@celery_app.task
def prepare_events(parameters: dict):
    params = EventRequestParameters(**parameters)
    events = crud.get_approved_events(params)

    if not events:
        return {"message": "No events to remake posts."}

    update_tasks = chord(
        (chain(
            ai_update_event.s(event),
            update_event.s(event['id'])
        ) for event in events),
        remake_events.s()
    )

    task_group = update_tasks.apply_async()
    return {"message": "AI update started.", "task_id": task_group.id}


@celery_app.task
def prepare_unprepared_events(limit: int = 5):
    """Beat task: prepare events where is_ready IS NULL (draft, not yet processed by AI)."""
    events = crud.get_unprepared_events(limit=limit)

    if not events:
        log.info("No unprepared events found.")
        return {"message": "No unprepared events.", "count": 0}

    log.info(f"Preparing {len(events)} unprepared events.")

    update_tasks = chord(
        (chain(
            ai_update_event.s(event),
            update_event.s(event['id'])
        ) for event in events),
        remake_events.s()
    )

    task_group = update_tasks.apply_async()
    return {
        "message": f"AI prepare started for {len(events)} events.",
        "task_id": task_group.id,
    }


@celery_app.task
def auto_promote_by_score(
    min_score: int = 70,
    limit: int = 20,
    uncategorized_min_score: int = 80,
    social_min_score: int = 80,
):
    """Переносит высокоскоринговые события из NotApproved в Events2Posts."""
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
def distribute_event_queue(protect_first: int = 10):
    """Переупорядочивает очередь публикации для разнообразия контента."""
    reordered = crud.distribute_event_queue(protect_first=protect_first)
    log.info(f"Reordered {reordered} events in posting queue")
    return {"reordered_count": reordered}


@celery_app.task
def auto_moderate_mid_score_events(
    min_score: int = 40, max_score: int = 69, sample_size: int = 10
):
    """AI-модерация случайной выборки событий со средним score."""
    # Автоотклонение мусора (score < min_score)
    rejected_count = crud.auto_reject_low_score_events(max_score=min_score - 1)
    log.info(f"Auto-rejected {rejected_count} events with score < {min_score}")

    # Случайная выборка для AI-модерации
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
            return {**new_event_data, "event_id": event_id}

    return {"message": f"Skipping event {event_id}, no update data"}


@celery_app.task
def remake_event(*event):
    full_event = {}
    for e in event:
        if isinstance(e, dict):
            full_event.update(e)

    if 'id' in full_event.keys():
        dsn_site_session.make_post_text([full_event['id']])


@celery_app.task
def remake_events(events):
    event_ids = [event.get('id') or event.get('event_id') for event in events if event.get('id') or event.get('event_id')]

    if event_ids:
        dsn_site_session.make_post_text(event_ids)


@celery_app.task
def get_posted_events(parameters: dict):
    params = EventRequestParameters(**parameters).with_defaults()

    events = crud.get_events_by_date_and_category(params)
    result = {
        'request': parameters,
        'events': events
    }
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

        send_message_to_telegram.apply_async(args=[text_message, reminder['telegram_id']], eta=remind_datetime)


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
def content_generator_generate_post(post_template_id: int, event_selection_id: int, generated_by_id: int):
    generator_post = GeneratorPost()
    post = generator_post.generate_post_by_template(post_template_id, event_selection_id, generated_by_id)
    return post

@celery_app.task
def content_generator_generate_post_ai(event_selection_id: int = None, event_ids: list = None, post_template_id: int = None, title: str = None):
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
        if not image_url: continue

        result = utils.process_image_from_url(image_url=image_url)
        crud.update_image_events(event['id'], result['url'], s3_key=result.get('key'))



@celery_app.task
def recalculate_scores_bulk(table: str = "events_eventsnotapprovednew", ids: list = None, force: bool = False):
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
        return {"status": "skipped", "reason": "insufficient_data",
                "positive": pos_count, "negative": neg_count}

    base_config = getattr(settings, "scoring", {})
    adaptive = calculate_adaptive_config(data["positive"], data["negative"], base_config)
    save_to_redis(redis_client, adaptive)

    log.info(f"update_adaptive_scoring done: {adaptive.get('source_scores', {})} sources, "
             f"{adaptive.get('category_scores', {})} categories")
    return {
        "status": "ok",
        "positive": pos_count,
        "negative": neg_count,
        "adaptive_source_scores": adaptive.get("source_scores"),
        "adaptive_category_scores": adaptive.get("category_scores"),
        "suggested_boost": adaptive.get("suggested_boost_keywords"),
        "suggested_penalty": adaptive.get("suggested_penalty_keywords"),
    }
