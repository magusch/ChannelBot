import hashlib
import json
import os
from datetime import datetime

from celery.result import AsyncResult
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from davai_s_nami_bot import crud
from davai_s_nami_bot.api import register_routers
from davai_s_nami_bot.celery_app import celery_app, redis_client
from davai_s_nami_bot.pydantic_models import EventRequestParameters, PlaceRequestParameters

OPENAPI_TAGS = [
    {
        "name": "Auth",
        "description": "Registration, login, JWT tokens, Telegram WebApp authorization.",
    },
    {
        "name": "Users",
        "description": "User profile management and favourite events.",
    },
    {
        "name": "Events",
        "description": "Retrieve events by filters, caching (10 min TTL).",
    },
    {
        "name": "Events (legacy)",
        "description": "Legacy event endpoints from main.py. Will be moved to `/api/events/`.",
    },
    {
        "name": "Tasks",
        "description": "Run and monitor background Celery tasks: scraping, scoring, publication queue.",
    },
    {
        "name": "Tasks (legacy)",
        "description": "Legacy task endpoints from main.py. Will be moved to `/api/tasks/`.",
    },
    {
        "name": "AI",
        "description": "AI processing of events: moderation, text preparation, site scraping.",
    },
    {
        "name": "AI (legacy)",
        "description": "Legacy AI endpoints from main.py. Will be moved to `/api/ai/`.",
    },
    {
        "name": "Images",
        "description": "Upload event images to AWS S3.",
    },
    {
        "name": "Images (legacy)",
        "description": "Legacy image endpoints from main.py.",
    },
    {
        "name": "Content Generator",
        "description": "Post generation: event selection by filter, templates, AI generation.",
    },
    {
        "name": "Content Generator (legacy)",
        "description": "Legacy content generator endpoints from main.py.",
    },
    {
        "name": "Places",
        "description": "Places: search, metro filtering, caching.",
    },
    {
        "name": "Places (legacy)",
        "description": "Legacy place endpoints from main.py.",
    },
    {
        "name": "Search",
        "description": "Full-text search across events and places.",
    },
    {
        "name": "Search (legacy)",
        "description": "Legacy search endpoint from main.py.",
    },
]

app = FastAPI(
    title="ChannelBot API",
    description=(
        "API for automating scraping, processing, and publishing events "
        "to Telegram/VK channels.\n\n"
        "## Authentication\n\n"
        "- **API Token** (`Bearer`): for all endpoints except auth. "
        "Passed in the `Authorization: Bearer <API_TOKEN>` header.\n"
        "- **JWT** (`OAuth2`): for user endpoints (`/auth`, `/users`). "
        "Obtained via `/api/auth/login`.\n\n"
        "## Architecture\n\n"
        "Endpoints marked **(legacy)** live in `main.py` and will be "
        "moved to modular routers (`/api/`). "
        "New routers are in `davai_s_nami_bot/api/`.\n\n"
        "Background tasks run via **Celery** — "
        "the endpoint returns a `task_id`, status is checked via "
        "`GET /api/tasks/status/{task_id}`."
    ),
    version="2.15.0",
    openapi_tags=OPENAPI_TAGS,
)

register_routers(app, prefix="/api")

origins = [
    "http://example.com",
    "http://localhost:3000",
    "https://davai-s-nami.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allowed origins
    allow_credentials=True,
    allow_methods=["*"],  # Allowed methods (GET, POST, etc.)
    allow_headers=["*"],  # Allowed headers
)

security = HTTPBearer()

API_TOKEN = os.environ.get('API_TOKEN', 'your-secure-api-token')


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    if token == API_TOKEN:
        return API_TOKEN
    else:
        raise HTTPException(status_code=403, detail="Invalid token")


def get_cache_key(params: dict):
    key = json.dumps(params, sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()


def serialize_datetime(obj):
    """Serialize datetime to a string."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


async def log_api_request(request: Request, data=None):
    """
    Common function to log API requests
    Args:
        request: FastAPI request object
        data: Request data (can be None for empty requests)
    """
    celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.log_api_request',
        args=[
            {
                'ip': request.client.host,
                'endpoint': str(request.url),
                'method': request.method,
                'status_code': 200,
                'timestamp': datetime.now().isoformat(),
                'user_agent': request.headers.get('User-Agent'),
                'request_data': json.dumps(data) if data is not None else None,
            }
        ],
    )


@app.post('/api/schedule-update-events/', tags=["Tasks (legacy)"],
           summary="Update events",
           description="Run the Celery task that updates events (approved + not_approved organizations).")
async def update_events(request: Request, token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_events',
    )
    return {'message': 'Task Update events added to queue', 'task_id': task.id}


@app.post('/api/schedule-full-update/', tags=["Tasks (legacy)"],
           summary="Full update",
           description="Full cycle: scraping all sources + processing + scoring.")
async def full_update(request: Request, token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.full_update',
    )
    return {'message': 'Task Full Update added to queue', 'task_id': task.id}


@app.post('/api/get_event_from_url/', tags=["Tasks (legacy)"],
           summary="Event by URL",
           description="Scrape an event from a direct link to the source.")
async def event_from_url(request: Request, token: str = Depends(verify_token)):
    data = await request.json()
    if 'event_url' in data.keys():
        event_url = data['event_url']
    else:
        event_url = None

    await log_api_request(request, data)

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.events_from_url',
        args=[event_url],
    )
    return {'message': 'Task updating from url added to queue', 'task_id': task.id}


@app.get("/api/status/{task_id}", tags=["Tasks (legacy)"],
         summary="Task status",
         description="Check Celery task status by task_id. Returns: success/failure/PENDING.")
async def get_status(task_id: str, token: str = Depends(verify_token)):
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

@app.get("/", tags=["Health"], summary="Health check")
async def index():
    return {'message': 'Hello. How are you?'}


@app.post('/api/param/', tags=["Tasks (legacy)"],
           summary="Update parameters",
           description="Update DSN parameters from Redis.")
async def update_parameters(token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_parameters',
    )
    return {'message': 'Task PARAMETERS added to queue', 'task_id': task.id}


@app.get('/api/check_ai_balance/', tags=["AI (legacy)"],
         summary="Check AI balance",
         description="Check the balance of AI providers (OpenAI, Anthropic).")
async def check_ai_balance(token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.check_ai_balance',
    )
    return {'message': 'Task check AI balance added to queue', 'task_id': task.id}


@app.post('/api/ai_update_event/', tags=["AI (legacy)"],
           summary="AI event update",
           description="Update event texts via AI (Claude/OpenAI).")
async def new_event_from_data(request: Request, token: str = Depends(verify_token), ):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.ai_update_event',
        args=[data['event'], data['is_new']],
    )
    return {'message': 'Task NEW EVENT added to queue', 'task_id': task.id}


@app.post('/api/ai_moderate_events/', tags=["AI (legacy)"],
           summary="AI moderation of events",
           description="Moderate a list of events via AI. Optionally accepts examples.")
async def moderate_events(request: Request, token: str = Depends(verify_token), ):
    data = await request.json()
    args = []
    if 'events' in data.keys():
        args.append(data['events'])
        if 'examples' in data.keys():
            args.append(data['examples'])

        task = celery_app.send_task(
            'davai_s_nami_bot.celery_tasks.ai_moderate_events',
            args=args,
        )
        return {'message': 'Task moderation of events added to queue', 'task_id': task.id}
    else:
        return {'message': 'There are not events for Task moderation of events'}


@app.post('/api/ai_moderate_not_approved_events/', tags=["AI (legacy)"],
           summary="AI moderation of not-approved events",
           description="Moderate events from EventsNotApproved via AI.")
async def moderate_not_approved_events(request: Request, token: str = Depends(verify_token), ):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.ai_moderate_not_approved_events',
        args=[data],
    )
    return {'message': 'Task moderate not approved events added to queue', 'task_id': task.id}


@app.post('/api/prepare_events/', tags=["AI (legacy)"],
           summary="AI event preparation",
           description="Prepare event texts for publication via AI.")
async def prepare_events(request: Request, token: str = Depends(verify_token), ):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.prepare_events',
        args=[data],
    )
    return {'message': 'Task prepare events added to queue', 'task_id': task.id}


@app.post('/api/new_event_from_sites/', tags=["Tasks (legacy)"],
           summary="Scrape from sites",
           description="Start scraping events from the specified source sites.")
async def new_event_from_sites(request: Request, token: str = Depends(verify_token)):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_event_from_sites',
        args=[data['sites'], data['days']],
    )
    return {'message': 'Task for escrape new event from sites added to queue', 'task_id': task.id}


@app.post('/api/get_valid_events/', tags=["Events (legacy)"],
           summary="List events",
           description="Retrieve events with filters (date, category, place, price). Cached for 10 min.")
async def get_valid_events(request: Request, token: str = Depends(verify_token)):

    data = await request.json()
    cache_key = get_cache_key(data)
    cached_data = redis_client.get(cache_key)

    await log_api_request(request, data)

    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    params = EventRequestParameters(**data).with_defaults()

    result = crud.get_events_by_date_and_category(params)
    redis_client.setex(cache_key, 60 * 10, json.dumps(result, default=serialize_datetime))
    return {"status": "success", "result": result}


@app.post("/api/get_valid_event/{event_id}", tags=["Events (legacy)"],
           summary="Event by ID",
           description="Retrieve an event by ID. Cached for 10 min.")
async def get_valid_event_by_id(
        event_id: int,
        request: Request,
        token: str = Depends(verify_token),
    ):
    await log_api_request(request, {"ids": [event_id]})

    cached_data = redis_client.get(f"event_{event_id}")
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    data = {"ids": [event_id]}

    params = EventRequestParameters(**data).with_defaults()
    result = crud.get_events_by_date_and_category(params)
    redis_client.setex(f"event_{event_id}", 60 * 10, json.dumps(result, default=serialize_datetime))

    return {"status": "success", "result": result}


@app.post('/api/get_places/', tags=["Places (legacy)"],
           summary="List places",
           description="Retrieve places with metro filtering. Cached for 10 min.")
async def get_places(
        request: Request,
        token: str = Depends(verify_token),
    ):
    data = await request.json()
    await log_api_request(request, data)
    cache_key = get_cache_key(data)
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    params = PlaceRequestParameters(**data)
    places = crud.get_places(params)
    redis_client.setex(cache_key, 60 * 10, json.dumps(places, default=serialize_datetime))
    result = {
        "status": "success",
        "result": {
            'request': data,
            'places': places
        }
    }
    return result


@app.post("/api/get_place/{place_id}", tags=["Places (legacy)"],
           summary="Place by ID",
           description="Retrieve a place by ID. Cached for 10 min.")
async def get_place_by_id(
        place_id: int,
        request: Request,
        token: str = Depends(verify_token),
    ):

    await log_api_request(request, {'place_id': place_id})
    cached_data = redis_client.get(f"place_{place_id}")
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    data = {"ids": [place_id]}

    params = PlaceRequestParameters(**data)
    places = crud.get_places(params)
    redis_client.setex(f"place_{place_id}", 60 * 10, json.dumps(places, default=serialize_datetime))
    result = {
        "status": "success",
        "result": {
            'request': data,
            'places': places
        }
    }
    return result


@app.post('/api/get_exhibitions/', tags=["Events (legacy)"],
           summary="Get exhibitions",
           description="Trigger the Celery task that retrieves current exhibitions.")
async def get_exhibitions(request: Request, token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.get_exhibitions_celery',
    )
    await log_api_request(request)
    return {'message': 'GET Exhibitions', 'task_id': task.id}


@app.get("/api/search/", tags=["Search (legacy)"],
         summary="Search events/places",
         description="Full-text search. type: `event`, `place` or `all`.")
async def search(query: str, limit: int = 10, type: str = 'event',
        request: Request = None, token: str = Depends(verify_token)):
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


@app.post('/api/upload_image_to_s3/', tags=["Images (legacy)"],
           summary="Upload an image to S3",
           description="Upload a single image by URL to AWS S3.")
async def upload_image_to_s3(request: Request = None, token: str = Depends(verify_token)):
    data = await request.json()
    img_url = None
    if 'img_url' in data.keys():
        img_url = data['img_url']


    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.upload_image_to_s3',
        args=[img_url],
    )
    return {'message': 'Task upload images to s3 to queue', 'task_id': task.id}


@app.post('/api/upload_event_images_to_s3/', tags=["Images (legacy)"],
           summary="Upload event images to S3",
           description="Bulk upload of event images to AWS S3 by a list of IDs.")
async def upload_event_images_to_s3(request: Request = None, token: str = Depends(verify_token)):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.upload_event_images_to_s3',
        args=[data['event_ids']],
    )
    return {'message': 'Task upload event images to s3 to queue', 'task_id': task.id}


###--> Content generator START <--###
@app.post('/api/content_generator_event_selection/', tags=["Content Generator (legacy)"],
           summary="Event selection by filter",
           description="Create an event selection by filter configuration (filter_set_id).")
async def content_generator_event_selection(request: Request, token: str = Depends(verify_token)):
    data = await request.json()
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.content_generator_event_selection',
        args=[data['filter_set_id']],
    )
    return {'message': 'Task content generator event selection added to queue', 'task_id': task.id}


@app.post('/api/content_generator_generate_post/', tags=["Content Generator (legacy)"],
           summary="Generate post",
           description="Generate a post from a template and an event selection.")
async def content_generator_generate_post(request: Request, token: str = Depends(verify_token)):
    data = await request.json()
    generated_by_id = data.get('generated_by_id') or None
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.content_generator_generate_post',
        args=[data['event_selection_id'], data['post_template_id'], generated_by_id],
    )
    return {'message': 'Task content generator generate post added to queue', 'task_id': task.id}

###--> Content generator END <--###

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
