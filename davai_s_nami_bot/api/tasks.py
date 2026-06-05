import json

from fastapi import APIRouter, Depends, Request
from celery.result import AsyncResult

from ..celery_app import celery_app, redis_client
from .dependencies import verify_token, serialize_datetime, log_api_request
from .schemas import EventUrlRequest, TaskResponse, RecalculateScoresRequest

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
    dependencies=[Depends(verify_token)],
)


@router.post("/schedule-update-events/", response_model=TaskResponse,
              summary="Update events",
              description="Scrape and process events from approved and not_approved organizations.")
async def update_events(request: Request):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_events',
    )
    return TaskResponse(message='Task Update events added to queue', task_id=task.id)


@router.post("/schedule-full-update/", response_model=TaskResponse,
              summary="Full update",
              description="Full cycle: scraping → scoring → processing. Calls subtasks: update_parameters, is_empty_check, move_approved, events_from_url, update_events.")
async def full_update(request: Request):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.full_update',
    )
    return TaskResponse(message='Task Full Update added to queue', task_id=task.id)


@router.post("/get-event-from-url/", response_model=TaskResponse,
              summary="Event by URL",
              description="Scrape an event from a direct link to the source.")
async def event_from_url(body: EventUrlRequest, request: Request):
    await log_api_request(request, body.model_dump())

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.events_from_url',
        args=[body.event_url],
    )
    return TaskResponse(message='Task updating from url added to queue', task_id=task.id)


@router.get("/status/{task_id}",
             summary="Task status",
             description="Check the status of a Celery task. Returns: success (with result), failure (with error), or the current state (PENDING/STARTED).")
async def get_status(task_id: str):
    params = redis_client.get(task_id)
    result = AsyncResult(task_id, app=celery_app)
    if result.state == 'SUCCESS':
        if params:
            redis_client.setex(params, 60 * 60, json.dumps(result.result, default=serialize_datetime))
        return {"status": "success", "result": result.result}
    elif result.state == 'FAILURE':
        return {"status": "failure", "error": str(result.info)}
    else:
        return {"status": result.state}


@router.delete("/{task_id}",
                summary="Cancel a task",
                description=(
                    "Revokes a Celery task. If the task is in PENDING/RETRY — it will "
                    "not be executed. If it is already running in a worker — the current "
                    "run will finish naturally (terminate=False), but further "
                    "automatic retries will not start. "
                    "Used by the frontend during fallback to local processing, "
                    "so that a server-side retry does not overwrite the local result in the DB."
                ))
async def cancel_task(task_id: str):
    celery_app.control.revoke(task_id)
    return {"status": "revoked", "task_id": task_id}


@router.post("/param/", response_model=TaskResponse,
              summary="Update parameters",
              description="Update DSN parameters from Redis.")
async def update_parameters():
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_parameters',
    )
    return TaskResponse(message='Task PARAMETERS added to queue', task_id=task.id)


@router.get("/check-ai-balance/", response_model=TaskResponse,
             summary="Check AI balance",
             description="Check the balance of AI providers (OpenAI, Anthropic).")
async def check_ai_balance():
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.check_ai_balance',
    )
    return TaskResponse(message='Task check AI balance added to queue', task_id=task.id)


@router.post("/get-exhibitions/", response_model=TaskResponse,
              summary="Get exhibitions",
              description="Trigger the task that retrieves the current exhibitions.")
async def get_exhibitions(request: Request):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.get_exhibitions_celery',
    )
    await log_api_request(request)
    return TaskResponse(message='GET Exhibitions', task_id=task.id)


@router.post("/recalculate-scores/", response_model=TaskResponse)
async def recalculate_scores(body: RecalculateScoresRequest, request: Request):
    """Recalculate scores (and resolve place_id) for events.

    - ids=null  → all events where score IS NULL
    - ids=[...] → only those specific IDs (regardless of current score)
    """
    await log_api_request(request, body.model_dump())
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.recalculate_scores_bulk',
        kwargs={"table": body.table, "ids": body.ids, "force": body.force},
    )
    msg = f'Recalculate scores queued for {len(body.ids)} events' if body.ids else 'Recalculate scores (null only) queued'
    return TaskResponse(message=msg, task_id=task.id)


@router.post("/update-adaptive-scoring/", response_model=TaskResponse)
async def update_adaptive_scoring(request: Request):
    """Trigger adaptive scoring recalculation (normally runs weekly)."""
    await log_api_request(request)
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_adaptive_scoring',
    )
    return TaskResponse(message='Adaptive scoring update queued', task_id=task.id)


@router.post("/prepare-unprepared-events/", response_model=TaskResponse)
async def prepare_unprepared_events(request: Request):
    """AI preparation of events with is_ready=NULL."""
    await log_api_request(request)
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.prepare_unprepared_events',
        kwargs={'limit': 15},
    )
    return TaskResponse(message='Prepare unprepared events queued', task_id=task.id)


@router.post("/auto-promote-by-score/", response_model=TaskResponse)
async def auto_promote_by_score(request: Request):
    """Move high-scoring events from NotApproved to Events2Posts."""
    await log_api_request(request)
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.auto_promote_by_score',
        kwargs={'min_score': 70, 'limit': 20},
    )
    return TaskResponse(message='Auto-promote by score queued', task_id=task.id)


@router.post("/distribute-event-queue/", response_model=TaskResponse)
async def distribute_event_queue(request: Request):
    """Reorder the publication queue for variety."""
    await log_api_request(request)
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.distribute_event_queue',
        kwargs={'protect_first': 10},
    )
    return TaskResponse(message='Distribute event queue queued', task_id=task.id)


@router.post("/auto-moderate-mid-score/", response_model=TaskResponse)
async def auto_moderate_mid_score(request: Request):
    """AI moderation of mid-score events (40-69)."""
    await log_api_request(request)
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.auto_moderate_mid_score_events',
        kwargs={'min_score': 40, 'max_score': 69, 'sample_size': 10},
    )
    return TaskResponse(message='Auto-moderate mid-score queued', task_id=task.id)


@router.get("/adaptive-scoring/")
async def get_adaptive_scoring():
    """View current adaptive scoring config from Redis."""
    from davai_s_nami_bot.adaptive_scoring import load_from_redis
    from davai_s_nami_bot.celery_app import redis_client
    adaptive = load_from_redis(redis_client)
    if not adaptive:
        return {"status": "no_adaptive_config", "message": "Not calculated yet or expired"}
    return adaptive
