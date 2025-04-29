import datetime
from typing import Any, List

import pytz


from .events import Event
from .logger import catch_exceptions, get_logger
from . import crud


DEFAULT_UPDATING_STRFTIME = "00:00"

log = get_logger(__file__)


def next_event_to_channel():
    """
    The first event from event2post table for posting

    Event search criteria:
    - Field `status` has `ReadyToPost` value
    - Datetime now is similar to `post_date`
    """
    events = crud.get_event_to_post_now()

    if events is None or len(events) == 0:
        event = None
    else:
        # Events are already filtered by status and sorted by queue in the database query
        event = events[0]
        crud.set_status(
            event_id=event.event_id, status="Posted"
        )

    return event


def get_new_events(events: List[Event]) -> List[Event]:
    all_events = crud.get_events_from_all_tables()
    
    # Получаем множество event_id из всех событий
    existing_ids = set(event.event_id for event in all_events)
    
    # Фильтруем события, оставляя только те, которых нет в базе
    new_events = [event for event in events if event.event_id not in existing_ids]

    return new_events


def not_published_count():
    events = crud.get_ready_to_post_events()
    
    return len(events)


def events_count():
    # Get events from all tables using CRUD
    all_events = crud.get_events_from_all_tables()
    return len(all_events)


columns_for_posting_time = ["post_date", "title", "event_id"]


def next_posting_time(reference):
    all_events = crud.get_ready_to_post_events()
    if len(all_events) == 0:
        return None

    # Convert string dates to datetime objects and filter events
    events_to_post = []
    for event in all_events:
        if hasattr(event, 'post_date') and event.post_date:
            # Convert to datetime if it's a string
            if isinstance(event.post_date, str):
                post_date = datetime.datetime.fromisoformat(event.post_date.replace('Z', '+00:00'))
            else:
                post_date = event.post_date
                
            # Convert to the same timezone as reference
            if post_date.tzinfo is None:
                post_date = pytz.UTC.localize(post_date)
            post_date = post_date.astimezone(reference.tzinfo)
            
            if post_date >= reference:
                events_to_post.append((post_date, event))
    
    if not events_to_post:
        return None
        
    # Sort by post_date and return the earliest one
    events_to_post.sort(key=lambda x: x[0])
    return events_to_post[0][0]


def next_updating_time(reference):
    hour, minute = DEFAULT_UPDATING_STRFTIME.split(":")
    hour, minute = int(hour), int(minute)
    update_time = reference.replace(
        hour=hour, minute=minute
    )

    if reference.hour > hour or (
            reference.hour == hour and reference.minute > minute
    ):
        update_time += datetime.timedelta(days=1)

    return update_time


def next_task_time(msk_today):
    task_time = None
    posting_time = next_posting_time(reference=msk_today)
    update_time = next_updating_time(reference=msk_today)

    if posting_time is None and update_time is None:
        # something bad happening
        raise ValueError("Don't found event for posting and updating time!")

    if posting_time is None:
        log.warning("Don't event for posting! Continue with updating time.")
        task_time = update_time

    elif update_time is None:
        log.warning("Don't found updating time! Continue with posting time.")
        task_time = posting_time

    elif update_time - msk_today < posting_time - msk_today:
        task_time = update_time

    else:
        task_time = posting_time

    return task_time
