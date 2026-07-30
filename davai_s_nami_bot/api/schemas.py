from typing import List, Optional, Union

from pydantic import BaseModel, Field


# Celery tasks
class EventUrlRequest(BaseModel):
    """Request to scrape an event by URL."""
    event_url: Optional[str] = Field(None, description="Event URL on the source site")


class TaskResponse(BaseModel):
    """Standard response when a Celery task is queued."""
    message: str = Field(..., description="Queued task description")
    task_id: str = Field(..., description="Poll via GET /api/tasks/status/{task_id}")


# AI
class AiUpdateEventRequest(BaseModel):
    """Request to update an event via AI."""

    event: dict = Field(..., description="Event dict (Events2Posts fields)")
    is_new: int = Field(0, description="1=new, 0=update")


class AiModerateEventsRequest(BaseModel):
    """Request to AI-moderate a list of events."""

    events: List[dict] = Field(..., description="Events to moderate")
    examples: Optional[List[dict]] = Field(None, description="Few-shot examples")


# Scraping
class NewEventFromSitesRequest(BaseModel):
    """Request to scrape events from the specified sites."""

    sites: List[str] = Field(..., description="Source names (timepad, radario, vk, telegram, …)")
    days: int = Field(7, description="Scraping depth in days")


# Images
class UploadImageRequest(BaseModel):
    """Request to upload an image to S3."""

    img_url: Optional[str] = Field(None, description="Image URL")


class UploadEventImagesRequest(BaseModel):
    """Request to bulk-upload event images."""

    event_ids: List[int] = Field(..., description="Events2Posts IDs")


# Scoring
class RecalculateScoresRequest(BaseModel):
    """Request to recalculate event scoring."""

    ids: Optional[List[int]] = Field(None, description="Event IDs (NULL = all where score IS NULL)")
    table: str = Field(
        "events_eventsnotapprovednew",
        description="events_eventsnotapprovednew or events_events2post",
    )
    force: bool = Field(False, description="Recalculate even if score is set")


# Content generator
class ContentGeneratorEventSelectionRequest(BaseModel):
    """Request to create an event selection by filter."""

    filter_set_id: int = Field(..., description="ContentGeneratorFilterSet ID")


class ContentGeneratorGeneratePostRequest(BaseModel):
    """Request to generate a post from a template."""

    event_selection_id: int = Field(..., description="Event selection ID")
    post_template_id: int = Field(..., description="Post template ID")
    generated_by_id: Optional[int] = Field(None, description="Source post ID (for regeneration)")


class BulkCreatePostRequest(BaseModel):
    """Bulk make-post (and optional save) request."""

    events: List[dict] = Field(..., description="Event dicts (as /events/make_post)")
    save: bool = Field(False, description="Insert into Events2Posts; else preview")
    status: str = Field(
        'ReadyToPost', description="Status when save=true (ReadyToPost/OnlyApi/draft)"
    )


class ContentGeneratorGeneratePostAIRequest(BaseModel):
    """Request to AI-generate a post."""

    event_selection_id: Optional[int] = Field(None, description="Event selection ID (or event_ids)")
    event_ids: Optional[List[int]] = Field(None, description="Event IDs (alt to selection)")
    post_template_id: Optional[int] = Field(None, description="Post template ID (optional)")
    title: Optional[str] = Field(None, description="Post title (optional)")


# Similar events (embedding-based)
class SimilarEventsResult(BaseModel):
    """Envelope shared between the hot (success) and cold (pending) responses."""

    events: List[dict] = Field(...,
        description="Similar events by ascending cosine distance; each has a `distance` field"
    )
    total_count: int = Field(..., description="Number of similar events returned")
    request: dict = Field(...,
        description="Request echo + diagnostics (embedding_model / 'reason' on miss)"
    )


class SemanticSearchRequest(BaseModel):
    """Natural-language event search via POST /search/semantic."""

    message: str = Field(..., description="Free-text query, e.g. 'джазовый концерт в выходные'")
    limit: int = Field(5, ge=1, le=50, description="Max events to return")
    max_distance: Optional[float] = Field(
        None, description="Cosine-distance cutoff (0=identical, 2=opposite); omit for none"
    )
    history: Optional[List[Union[str, dict]]] = Field(
        None,
        description="Prior turns (oldest→newest) for follow-ups; str or "
        "{'role': 'user'|'assistant', 'content': ...}. Only the last few are used.",
    )


class SimilarEventsResponse(BaseModel):
    """Response from GET /events/{event_id}/similar.

    status="success" — embedding existed, result is filled (200).
    status="pending" — embedding was missing, Celery task dispatched (202); poll
    /tasks/status/{task_id} and retry. Result envelope is still present with
    events=[] so the client can use a uniform shape.
    """

    status: str = Field(..., description="'success' (200) or 'pending' (202)")
    result: SimilarEventsResult
    task_id: Optional[str] = Field(None, description="Embed-job task id (only status='pending')")
    message: Optional[str] = Field(None, description="Human-readable hint (e.g. retry on pending)")
