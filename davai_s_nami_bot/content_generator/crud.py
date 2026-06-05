from ..database.database_orm import db_session, orm_to_dict
from .models import ContentGeneratorEventSelection, ContentGeneratorFilterSet, \
    ContentGeneratorEventSelectionSelectedEvents, ContentGeneratorPostTemplate, \
    ContentGeneratorGeneratedPost, PostingSchedule

from sqlalchemy import func


@db_session
def get_filter_set_by_id(db, filter_set_id: int) -> ContentGeneratorFilterSet:
    """Getting filter by ID"""
    if isinstance(filter_set_id, list):
        filter_set_id = filter_set_id[0]
    filter_set = db.query(ContentGeneratorFilterSet).filter_by(id=filter_set_id).first()
    if not filter_set:
        raise ValueError("Filter not found")
    return orm_to_dict(filter_set)


@db_session
def get_filter(db, filter_set_id: int = None) -> ContentGeneratorFilterSet:
    """Getting filter by ID or random filter if ID is not specified"""
    if not filter_set_id:
        filter_set = orm_to_dict(db.query(ContentGeneratorFilterSet).order_by(func.random()).first())
        if not filter_set:
            raise ValueError("No available filters")
    else:
        filter_set = get_filter_set_by_id(filter_set_id)
    return filter_set


@db_session
def create_event_selection(db, new_event_selection: dict):
    """Making new event selection based on filter and saving selected events"""
    
    new_event_selection = ContentGeneratorEventSelection(**new_event_selection)
    db.add(new_event_selection)
    db.commit()
    db.refresh(new_event_selection)
    return orm_to_dict(new_event_selection)

@db_session
def get_event_selection(db, event_selection_id: int = None) -> ContentGeneratorEventSelection:
    """Getting event selection by ID"""
    if event_selection_id:
        event_selection = db.query(ContentGeneratorEventSelection).get(event_selection_id)
    else:
        event_selection = db.query(ContentGeneratorEventSelection).order_by(func.random()).first()
    return orm_to_dict(event_selection)


@db_session
def add_selected_events(db, new_event_selection: ContentGeneratorEventSelection, filtered_events: list):
    """Saving filtered events"""
    for event in filtered_events:
        selected_event = ContentGeneratorEventSelectionSelectedEvents(
            events2post_id=event['id'],
            eventselection_id=new_event_selection['id']
        )
        db.add(selected_event)


@db_session
def get_selected_events(db, event_selection_id: int) -> list[ContentGeneratorEventSelectionSelectedEvents]:
    """Getting selected events"""
    selected_events = db.query(ContentGeneratorEventSelectionSelectedEvents).filter_by(eventselection_id=event_selection_id).all()
    return [event.events2post_id for event in selected_events]


@db_session
def create_generated_post(db, new_generated_post: dict):
    """Creating new generated post"""
    new_generated_post = ContentGeneratorGeneratedPost(**new_generated_post)
    db.add(new_generated_post)
    db.commit()
    db.refresh(new_generated_post)
    return orm_to_dict(new_generated_post)


@db_session
def get_post_template(db, post_template_id: int) -> ContentGeneratorPostTemplate:
    """Getting post template by ID"""
    if post_template_id:
        post_template = db.query(ContentGeneratorPostTemplate).get(post_template_id)
    else:
        post_template = db.query(ContentGeneratorPostTemplate).order_by(func.random()).first()
    return orm_to_dict(post_template)


@db_session
def create_posting_schedule(db, schedule_data: dict):
    """Create a new PostingSchedule entry"""
    schedule = PostingSchedule(**schedule_data)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return orm_to_dict(schedule)


@db_session
def get_pending_schedules(db, *, before_datetime=None, limit: int = 50):
    """Get pending, not posted schedules optionally before a datetime"""
    query = db.query(PostingSchedule).filter(PostingSchedule.is_posted == False)
    if before_datetime is not None:
        query = query.filter(PostingSchedule.scheduled_time <= before_datetime)
    query = query.order_by(PostingSchedule.scheduled_time.asc())
    if limit:
        query = query.limit(limit)
    schedules = query.all()
    return orm_to_dict(schedules)


@db_session
def get_next_schedule_per_platform(db):
    """Return the nearest schedule per platform that is not posted yet.
    Output: dict[platform] = schedule_dict
    """
    platforms = db.query(PostingSchedule.platform).filter(PostingSchedule.is_posted == False).distinct().all()
    platform_to_schedule = {}
    for (platform,) in platforms:
        schedule = (
            db.query(PostingSchedule)
            .filter(PostingSchedule.is_posted == False, PostingSchedule.platform == platform)
            .order_by(PostingSchedule.scheduled_time.asc())
            .first()
        )
        if schedule:
            platform_to_schedule[platform] = orm_to_dict(schedule)
    return platform_to_schedule


@db_session
def mark_schedule_posted(db, schedule_id: int, *, posted_at):
    schedule = db.query(PostingSchedule).get(schedule_id)
    if schedule:
        schedule.is_posted = True
        schedule.status = "Posted"
        schedule.posted_at = posted_at
        db.commit()
        # db.refresh(schedule)
        # return orm_to_dict(schedule)
    return None


@db_session
def increment_schedule_retry(db, schedule_id: int, error_message: str = None):
    schedule = db.query(PostingSchedule).get(schedule_id)
    if schedule:
        schedule.retry_count = (schedule.retry_count or 0) + 1
        if error_message:
            schedule.error_message = error_message
        db.commit()
        # db.refresh(schedule)
        # return orm_to_dict(schedule)
    return None


@db_session
def get_schedule_by_id(db, schedule_id: int):
    schedule = db.query(PostingSchedule).get(schedule_id)
    return orm_to_dict(schedule) if schedule else None


@db_session
def get_generated_post_by_id(db, generated_post_id: int):
    post = db.query(ContentGeneratorGeneratedPost).get(generated_post_id)
    return orm_to_dict(post) if post else None
