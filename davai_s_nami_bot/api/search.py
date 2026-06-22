from fastapi import APIRouter, Depends, Request, status

from .. import crud
from ..celery_app import celery_app
from .dependencies import log_api_request, verify_token
from .schemas import SemanticSearchRequest, TaskResponse

router = APIRouter(
    prefix="/search",
    tags=["Search"],
    dependencies=[Depends(verify_token)],
)


@router.get(
    "/", summary="Search events and places",
    description="Full-text search. `type`: `event` (default), `place`, or other for both.",
)
async def search(query: str, limit: int = 10, type: str = 'event', request: Request = None):
    events, places = [], []
    if type == 'event':
        events = crud.search_events_by_string(query, limit)
    elif type == 'place':
        places = crud.search_places_by_name(query, limit)
    else:
        events = crud.search_events_by_string(query, limit)
        places = crud.search_places_by_name(query, limit)
    await log_api_request(request, {'query': query, 'limit': limit, 'type': type})
    return {"events": events, "places": places}


@router.post(
    "/semantic/",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Natural-language semantic event search",
    description=(
        "Free-text query → LLM extracts semantic query + filters (dates, categories, "
        "price), embeds it, ranks events by cosine distance. Celery task: returns 202 "
        "with task_id; poll GET /tasks/status/{task_id}."
    ),
)
async def semantic_search(body: SemanticSearchRequest, request: Request):
    await log_api_request(request, body.model_dump())
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.semantic_event_search',
        kwargs={
            'message': body.message,
            'limit': body.limit,
            'max_distance': body.max_distance,
            'history': body.history,
        },
    )
    return TaskResponse(message='Semantic search queued', task_id=task.id)
