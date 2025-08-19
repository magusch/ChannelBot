from ..database.database_orm import db_session, orm_to_dict
from .models import ContentGeneratorEventSelection, ContentGeneratorFilterSet, \
    ContentGeneratorEventSelectionSelectedEvents, ContentGeneratorPostTemplate, ContentGeneratorGeneratedPost

from sqlalchemy import func


@db_session
def get_filter_set_by_id(db, filter_set_id: int) -> ContentGeneratorFilterSet:
    """Getting filter by ID"""
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
    