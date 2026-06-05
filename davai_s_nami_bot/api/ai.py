from fastapi import APIRouter, Depends, Request

from ..celery_app import celery_app
from .dependencies import verify_token
from .schemas import (
    AiUpdateEventRequest,
    AiModerateEventsRequest,
    NewEventFromSitesRequest,
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

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.prepare_events',
        args=[data],
    )
    return TaskResponse(message='Task prepare events added to queue', task_id=task.id)


@router.post("/new-event-from-sites/", response_model=TaskResponse,
              summary="Scrape from sites",
              description="Start scraping events from the specified source sites. Sources: timepad, radario, ticketscloud, qtickets, mts, kassir, culture, cfg, vk, telegram.")
async def new_event_from_sites(body: NewEventFromSitesRequest):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_event_from_sites',
        args=[body.sites, body.days],
    )
    return TaskResponse(message='Task for escrape new event from sites added to queue', task_id=task.id)
