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
              summary="AI обновление события",
              description="Обновление текстов мероприятия через AI (Claude/OpenAI).")
async def ai_update_event(body: AiUpdateEventRequest):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.ai_update_event',
        args=[body.event, body.is_new],
    )
    return TaskResponse(message='Task NEW EVENT added to queue', task_id=task.id)


@router.post("/moderate-events/",
              summary="AI модерация событий",
              description="Модерация списка мероприятий через AI. Опционально принимает примеры для few-shot.")
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
              summary="AI модерация необработанных",
              description="Модерация мероприятий из EventsNotApproved через AI.")
async def moderate_not_approved_events(request: Request):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.ai_moderate_not_approved_events',
        args=[data],
    )
    return TaskResponse(message='Task moderate not approved events added to queue', task_id=task.id)


@router.post("/prepare-events/", response_model=TaskResponse,
              summary="AI подготовка событий",
              description="Подготовка текстов мероприятий для публикации через AI.")
async def prepare_events(request: Request):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.prepare_events',
        args=[data],
    )
    return TaskResponse(message='Task prepare events added to queue', task_id=task.id)


@router.post("/new-event-from-sites/", response_model=TaskResponse,
              summary="Скрапинг с сайтов",
              description="Запуск скрапинга мероприятий с указанных сайтов-источников. Источники: timepad, radario, ticketscloud, qtickets, mts, kassir, culture, cfg, vk, telegram.")
async def new_event_from_sites(body: NewEventFromSitesRequest):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_event_from_sites',
        args=[body.sites, body.days],
    )
    return TaskResponse(message='Task for escrape new event from sites added to queue', task_id=task.id)
