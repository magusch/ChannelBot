import datetime, json
import requests
from bs4 import BeautifulSoup

from davai_s_nami_bot.celery_app import celery_app, redis_client
from celery import chain, chord

from datetime import datetime, timedelta

from .pydantic_models import EventRequestParameters, PlaceRequestParameters

from . import crud
from . import clients
from . import events
from . import utils
from . import dsn_site
from . import dsn_site_session
from .datetime_utils import get_msk_today, STRFTIME
from .logger import get_logger, LOG_FILE, log_task

from .helper.open_ai_helper import OpenAIHelper
from .helper.claude_helper import ClaudeHelper
# from .helper.open_ai_event_moderator import OpenAIEventModerator
from .helper.claude_event_moderator import ClaudeEventModerator

log = get_logger(__file__)
dev_channel = clients.DevClient()


@celery_app.task
def post_to_telegram():
    log.info(f"Posting event")

    event = dsn_site.next_event_to_channel()
    if event is not None:
        image_path = utils.prepare_image(event.image)
        clients.Clients().send_post(event=event, image_path=image_path)
        log.info("Event was posted")
    else:
        log.info("Event not found (or time was changed) or already posted")
    schedule_posting_tasks.apply_async()
    dev_channel.send_file(LOG_FILE, mode="r+b", with_remove=True)


@celery_app.task
def schedule_posting_tasks():
    log.info("Scheduling posting tasks based on database entries")
    msk_today = get_msk_today()
    event_time = dsn_site.next_posting_time(msk_today)

    if event_time is None:
        log.info("No events for posting")
        return
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
        if abs(current_scheduled_time_good - event_time) > timedelta(minutes=4):
            # Cancel old task time
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
    crud.remove_event_from_dsn_bot(msk_today + timedelta(hours=1))

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
    dsn_site_session.create_session()

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
        sites = ['timepad', 'ticketscloud', 'radario', 'vk', 'qtickets', 'mts', 'culture']
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


@celery_app.task
def ai_update_event(event={}, is_new=0):
    log.info("Start get post from url.")

    msk_today = get_msk_today()
    ai_helper = ClaudeHelper()

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

    moderator = ClaudeEventModerator()
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


@log_task
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
    dev_channel.send_text(msg)


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
def update_event(new_event_data, event_id):
    if new_event_data is not None:
        new_event_data = {k: v for k, v in new_event_data.items() if v}
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


