from typing import List, Optional

from pydantic import BaseModel, Field


# Celery tasks
class EventUrlRequest(BaseModel):
    """Request to scrape an event by URL."""
    event_url: Optional[str] = Field(None, description="URL of the event on the source site")


class TaskResponse(BaseModel):
    """Standard response when a Celery task is queued."""
    message: str = Field(..., description="Description of the queued task")
    task_id: str = Field(..., description="Celery task ID for tracking the status via GET /api/tasks/status/{task_id}")


# AI
class AiUpdateEventRequest(BaseModel):
    """Request to update an event via AI."""
    event: dict = Field(..., description="Event data (dict with fields from Events2Posts)")
    is_new: int = Field(0, description="1 — new event, 0 — update of an existing one")


class AiModerateEventsRequest(BaseModel):
    """Request to AI-moderate a list of events."""
    events: List[dict] = Field(..., description="List of events to moderate")
    examples: Optional[List[dict]] = Field(None, description="Examples for few-shot moderation (optional)")


# Scraping
class NewEventFromSitesRequest(BaseModel):
    """Request to scrape events from the specified sites."""
    sites: List[str] = Field(
        ...,
        description="List of sources: timepad, radario, ticketscloud, qtickets, mts, kassir, culture, cfg, vk, telegram",
    )
    days: int = Field(7, description="Scraping depth in days from the current date")


# Images
class UploadImageRequest(BaseModel):
    """Request to upload an image to S3."""
    img_url: Optional[str] = Field(None, description="Direct link to the image")


class UploadEventImagesRequest(BaseModel):
    """Request to bulk-upload event images."""
    event_ids: List[int] = Field(..., description="List of event IDs from Events2Posts")


# Scoring
class RecalculateScoresRequest(BaseModel):
    """Request to recalculate event scoring."""
    ids: Optional[List[int]] = Field(None, description="Event IDs. NULL — all rows where score IS NULL")
    table: str = Field(
        "events_eventsnotapprovednew",
        description="Table: events_eventsnotapprovednew or events_events2post",
    )
    force: bool = Field(False, description="True — recalculate even if the score is already set")


# Content generator
class ContentGeneratorEventSelectionRequest(BaseModel):
    """Request to create an event selection by filter."""
    filter_set_id: int = Field(..., description="ID of the filter configuration (ContentGeneratorFilterSet)")


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
    """Request to AI-generate a post."""
    event_selection_id: Optional[int] = Field(None, description="Event selection ID (or event_ids)")
    event_ids: Optional[List[int]] = Field(None, description="List of event IDs (alternative to event_selection_id)")
    post_template_id: Optional[int] = Field(None, description="Post template ID (optional for AI)")
    title: Optional[str] = Field(None, description="Post title (optional)")


# Similar events (embedding-based)
class SimilarEventsResult(BaseModel):
    """Envelope shared between the hot (success) and cold (pending) responses."""
    events: List[dict] = Field(..., description="Similar events, ordered by ascending cosine distance. Each event includes a `distance` field.")
    total_count: int = Field(..., description="Number of similar events returned")
    request: dict = Field(..., description="Echo of the request + diagnostics (embedding_model, or 'reason' on miss)")


class SimilarEventsResponse(BaseModel):
    """Response from GET /events/{event_id}/similar.

    status="success" — embedding existed, result is filled (200).
    status="pending" — embedding was missing, Celery task dispatched (202); poll
    /tasks/status/{task_id} and retry. Result envelope is still present with
    events=[] so the client can use a uniform shape.
    """
    status: str = Field(..., description="'success' (200) or 'pending' (202)")
    result: SimilarEventsResult
    task_id: Optional[str] = Field(None, description="Celery task id for the embed job (only when status='pending')")
    message: Optional[str] = Field(None, description="Human-readable hint (e.g. retry instructions on pending)")
