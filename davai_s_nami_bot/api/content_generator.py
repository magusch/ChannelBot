import json

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..celery_app import celery_app, redis_client
from ..content_generator import crud as cg_crud
from .dependencies import verify_token, log_api_request, serialize_datetime
from .schemas import (
    ContentGeneratorEventSelectionRequest,
    ContentGeneratorGeneratePostRequest,
    ContentGeneratorGeneratePostAIRequest,
    ContentGeneratorThemePostRequest,
    TaskResponse,
)

router = APIRouter(
    prefix="/content-generator",
    tags=["Content Generator"],
    dependencies=[Depends(verify_token)],
)


@router.post("/event-selection/", response_model=TaskResponse,
              summary="Event selection by filter",
              description="Create an event selection by filter configuration (ContentGeneratorFilterSet).")
async def content_generator_event_selection(body: ContentGeneratorEventSelectionRequest):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.content_generator_event_selection',
        args=[body.filter_set_id],
    )
    return TaskResponse(message='Task content generator event selection added to queue', task_id=task.id)


@router.post("/generate-post/", response_model=TaskResponse,
              summary="Generate post from template",
              description="Generate a post from a template (post_template_id) and an event selection (event_selection_id).")
async def content_generator_generate_post(body: ContentGeneratorGeneratePostRequest):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.content_generator_generate_post',
        args=[body.event_selection_id, body.post_template_id, body.generated_by_id],
    )
    return TaskResponse(message='Task content generator generate post added to queue', task_id=task.id)


@router.post("/generate-post-ai/", response_model=TaskResponse,
              summary="AI post generation",
              description="Generate a post via AI. You can pass event_selection_id or specific event_ids.")
async def content_generator_generate_post_ai(body: ContentGeneratorGeneratePostAIRequest):
    if not body.event_selection_id and not body.event_ids:
        raise HTTPException(status_code=400, detail="event_selection_id or event_ids required")
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.content_generator_generate_post_ai',
        args=[body.event_selection_id, body.event_ids, body.post_template_id, body.title],
    )
    return TaskResponse(message='Task AI post generation added to queue', task_id=task.id)


@router.post("/theme-post/", response_model=TaskResponse,
             summary="Themed digest post",
             description=(
                 "Build a themed digest: the theme text is embedded and matched "
                 "against event embeddings, the result is diversified and rendered "
                 "into a length-budgeted MarkdownV2 post. Without filter_set_id the "
                 "least-recently-posted active theme is used. dry_run returns the "
                 "rendered post without writing anything."
             ))
async def content_generator_theme_post(body: ContentGeneratorThemePostRequest):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.content_generator_theme_post',
        kwargs={'filter_set_id': body.filter_set_id, 'dry_run': body.dry_run},
    )
    return TaskResponse(message='Task theme post added to queue', task_id=task.id)


@router.get("/selection/{selection_id}/",
            summary="Events of a selection",
            description=(
                "Full event pool of a selection, in the order it was built, "
                "filtered to still-valid events. Backs the 'see the rest in the "
                "bot' link in a themed post: the post shows `shown_ids`, the bot "
                "shows everything. Cached for 10 min."
            ))
async def content_generator_selection(
    selection_id: int, request: Request, limit: int = 50
):
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 200",
        )

    await log_api_request(request, {"selection_id": selection_id, "limit": limit})

    cache_key = f"cg_selection_{selection_id}_{limit}"
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return {
            "status": "success",
            "message": 'cached',
            "result": json.loads(cached_data),
        }

    selection = cg_crud.get_event_selection(selection_id)
    if not selection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event selection not found",
        )

    found = cg_crud.get_selection_events(selection_id, limit=limit)

    settings_raw = selection.get('generation_settings')
    try:
        generation_settings = (
            json.loads(settings_raw)
            if isinstance(settings_raw, str)
            else (settings_raw or {})
        )
    except (json.JSONDecodeError, TypeError):
        generation_settings = {}

    result = {
        'events': found['events'],
        'total_count': found['total_count'],
        'selection': {
            'id': selection['id'],
            'name': selection['name'],
            'shown_ids': generation_settings.get('shown_ids') or [],
            # Stored events that are no longer showable.
            'dropped': found['dropped'],
        },
    }
    redis_client.setex(
        cache_key, 60 * 10, json.dumps(result, default=serialize_datetime)
    )
    return {"status": "success", "result": result}
