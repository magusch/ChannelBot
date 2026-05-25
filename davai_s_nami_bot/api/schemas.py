from typing import List, Optional

from pydantic import BaseModel


# Celery tasks
class EventUrlRequest(BaseModel):
    event_url: Optional[str] = None


class TaskResponse(BaseModel):
    message: str
    task_id: str


# AI
class AiUpdateEventRequest(BaseModel):
    event: dict
    is_new: int = 0


class AiModerateEventsRequest(BaseModel):
    events: List[dict]
    examples: Optional[List[dict]] = None


# Scraping
class NewEventFromSitesRequest(BaseModel):
    sites: List[str]
    days: int = 7


# Images
class UploadImageRequest(BaseModel):
    img_url: Optional[str] = None


class UploadEventImagesRequest(BaseModel):
    event_ids: List[int]


# Scoring
class RecalculateScoresRequest(BaseModel):
    ids: Optional[List[int]] = None
    table: str = "events_eventsnotapprovednew"
    force: bool = False  # if True — recalculate even if score is not None


# Content generator
class ContentGeneratorEventSelectionRequest(BaseModel):
    filter_set_id: int


class ContentGeneratorGeneratePostRequest(BaseModel):
    """Request to generate a post from a template."""
    event_selection_id: int = Field(..., description="Event selection ID")
    post_template_id: int = Field(..., description="Post template ID")
    generated_by_id: Optional[int] = Field(None, description="ID of a previously generated post (for regeneration)")


class BulkCreatePostRequest(BaseModel):
    """Bulk make-post (and optional save) request."""
    events: List[dict] = Field(..., description="List of event dicts (same shape as /events/make_post)")
    save: bool = Field(False, description="True — insert rows into Events2Posts; False — preview only")
    status: str = Field('ReadyToPost', description="Target status when save=true (e.g. 'ReadyToPost', 'OnlyApi', 'draft')")


class ContentGeneratorGeneratePostAIRequest(BaseModel):
    event_selection_id: Optional[int] = None
    event_ids: Optional[List[int]] = None
    post_template_id: Optional[int] = None
    title: Optional[str] = None
