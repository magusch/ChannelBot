from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..celery_app import celery_app
from ..database.models import Events2Posts, EventsNotApproved
from .city import enter_city_of
from .dependencies import log_api_request, verify_token
from .schemas import (
    AiUpdateEventRequest,
    AiModerateEventsRequest,
    ExtractEventsFromTextRequest,
    TaskResponse,
)

router = APIRouter(
    prefix="/ai",
    tags=["AI"],
    dependencies=[Depends(verify_token)],
)


@router.post("/update-event/", response_model=TaskResponse,
              summary="AI event update",
              description="Update event texts via AI (Claude/OpenAI).")
async def ai_update_event(body: AiUpdateEventRequest):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.ai_update_event',
        args=[body.event, body.is_new],
    )
    return TaskResponse(message='Task NEW EVENT added to queue', task_id=task.id)


async def queue_extract_events_from_text(body: ExtractEventsFromTextRequest, request: Request):
    """Queue AI extraction of events from raw text into EventsNotApproved."""
    if not body.content.strip():
        # A forwarded photo without a caption: nothing for the AI to read.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="content is empty"
        )
    await log_api_request(request, body.model_dump())
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.extract_events_from_text',
        args=[body.content, body.source, body.image],
    )
    return TaskResponse(message='Task extract events from text added to queue', task_id=task.id)


@router.post("/extract-events-from-text/", response_model=TaskResponse,
              summary="Events from raw text",
              description="AI reads a post text (e.g. a forwarded Telegram post), "
              "extracts events and saves them to EventsNotApproved (status 'new') "
              "of the request's city. Legacy alias: POST /api/create_post_by_ai/.")
async def extract_events_from_text(body: ExtractEventsFromTextRequest, request: Request):
    return await queue_extract_events_from_text(body, request)


@router.post("/moderate-events/",
              summary="AI moderation of events",
              description="Moderate a list of events via AI. Optionally accepts examples for few-shot.")
async def moderate_events(body: AiModerateEventsRequest):
    args = [body.events]
    if body.examples is not None:
        args.append(body.examples)

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.ai_moderate_events',
        args=args,
    )
    return TaskResponse(message='Task moderation of events added to queue', task_id=task.id)


@router.post("/moderate-not-approved-events/", response_model=TaskResponse,
              summary="AI moderation of not-approved events",
              description="Moderate events from EventsNotApproved via AI.")
async def moderate_not_approved_events(request: Request):
    data = await request.json()
    await enter_city_of(EventsNotApproved, (data or {}).get('ids') or [])

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.ai_moderate_not_approved_events',
        args=[data],
    )
    return TaskResponse(message='Task moderate not approved events added to queue', task_id=task.id)


@router.post("/prepare-events/", response_model=TaskResponse,
              summary="AI event preparation",
              description="Prepare event texts for publication via AI.")
async def prepare_events(request: Request):
    data = await request.json()
    await enter_city_of(Events2Posts, (data or {}).get('ids') or [])

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.prepare_events',
        args=[data],
    )
    return TaskResponse(message='Task prepare events added to queue', task_id=task.id)
