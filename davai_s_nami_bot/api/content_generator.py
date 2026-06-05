from fastapi import APIRouter, Depends

from ..celery_app import celery_app
from .dependencies import verify_token
from .schemas import (
    ContentGeneratorEventSelectionRequest,
    ContentGeneratorGeneratePostRequest,
    ContentGeneratorGeneratePostAIRequest,
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
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="event_selection_id or event_ids required")
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.content_generator_generate_post_ai',
        args=[body.event_selection_id, body.event_ids, body.post_template_id, body.title],
    )
    return TaskResponse(message='Task AI post generation added to queue', task_id=task.id)
