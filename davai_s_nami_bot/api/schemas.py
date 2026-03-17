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
    event_selection_id: int
    post_template_id: int
    generated_by_id: Optional[int] = None


class ContentGeneratorGeneratePostAIRequest(BaseModel):
    event_selection_id: Optional[int] = None
    event_ids: Optional[List[int]] = None
    post_template_id: Optional[int] = None
    title: Optional[str] = None
