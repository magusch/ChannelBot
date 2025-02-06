import os, json
import hashlib
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware

from davai_s_nami_bot.celery_app import celery_app, redis_client
from celery.result import AsyncResult

from davai_s_nami_bot import crud

from davai_s_nami_bot.pydantic_models import EventRequestParameters, PlaceRequestParameters

app = FastAPI()

origins = [
    "http://example.com",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Разрешенные источники
    allow_credentials=True,
    allow_methods=["*"],  # Разрешенные методы (GET, POST и т. д.)
    allow_headers=["*"],  # Разрешенные заголовки
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
    """Функция для сериализации datetime в строку"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


@app.post('/api/schedule-update-events/')
async def update_events(token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_events',
    )
    return {'message': 'Task Update events added to queue', 'task_id': task.id}


@app.post('/api/schedule-full-update/')
async def update_events(token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.full_update',
    )
    return {'message': 'Task Full Update added to queue', 'task_id': task.id}


@app.post('/api/get_event_from_url/')
async def event_from_url(request: Request, token: str = Depends(verify_token)):
    data = await request.json()
    if 'event_url' in data.keys():
        event_url = data['event_url']
    else:
        event_url = None

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.events_from_url',
        args=[event_url],
    )
    return {'message': 'Task updating from url added to queue', 'task_id': task.id}


@app.get("/api/status/{task_id}")
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

@app.get("/")
async def index():
    return {'message': 'Hello. How are you?'}


@app.post('/api/param/')
async def update_parameters(token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_parameters',
    )
    return {'message': 'Task PARAMETERS added to queue', 'task_id': task.id}


@app.post('/api/ai_update_event/')
async def new_event_from_data(request: Request, token: str = Depends(verify_token), ):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.ai_update_event',
        args=[data['event'], data['is_new']],
    )
    return {'message': 'Task NEW EVENT added to queue', 'task_id': task.id}


@app.post('/api/ai_moderate_events/')
async def moderate_events(request: Request, token: str = Depends(verify_token), ):
    data = await request.json()
    args = []
    if 'events' in data.keys:
        args.push(data['events'])
        if 'examples' in data.keys:
            args.push(data['examples'])

        task = celery_app.send_task(
            'davai_s_nami_bot.celery_tasks.ai_moderate_events',
            args=args,
        )
        return {'message': 'Task moderation of events added to queue', 'task_id': task.id}
    else:
        return {'message': 'There are not events for Task moderation of events'}


@app.post('/api/ai_moderate_not_approved_events/')
async def moderate_not_approved_events(request: Request, token: str = Depends(verify_token), ):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.ai_moderate_not_approved_events',
        args=[data],
    )
    return {'message': 'Task moderate not approved events added to queue', 'task_id': task.id}


@app.post('/api/new_event_from_sites/')
async def new_event_from_sites(request: Request, token: str = Depends(verify_token)):
    data = await request.json()

    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.update_event_from_sites',
        args=[data['sites'], data['days']],
    )
    return {'message': 'Task for escrape new event from sites added to queue', 'task_id': task.id}


@app.post('/api/get_valid_events/')
async def get_valid_events(request: Request, token: str = Depends(verify_token)):

    data = await request.json()
    cache_key = get_cache_key(data)
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    # task = celery_app.send_task(
    #     'davai_s_nami_bot.celery_tasks.get_posted_events',
    #     args=[data],
    # )
    # redis_client.setex(task.id, 60 * 10, cache_key)
    # return {'message': 'GET EVENTS', 'task_id': task.id}
    params = EventRequestParameters(**data).with_defaults()

    events = crud.get_events_by_date_and_category(params)
    redis_client.setex(cache_key, 60 * 10, json.dumps(events, default=serialize_datetime))
    result = {
        "status": "success",
        "result": {
            'request': data,
            'events': events
        }
    }
    return result


@app.post("/api/get_valid_event/{event_id}")
async def get_valid_event_by_id(
        event_id: int,
        token: str = Depends(verify_token),
    ):

    cached_data = redis_client.get(f"event_{event_id}")
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    data = {"ids": [event_id]}

    # task = celery_app.send_task(
    #     'davai_s_nami_bot.celery_tasks.get_posted_events',
    #     args=[data],
    # )
    # redis_client.setex(task.id, 60 * 10, f"event_{event_id}")
    # return {'message': 'GET EVENT by ID added to queue', 'task_id': task.id}
    params = EventRequestParameters(**data).with_defaults()
    events = crud.get_events_by_date_and_category(params)
    redis_client.setex(f"event_{event_id}", 60 * 10, json.dumps(events, default=serialize_datetime))
    result = {
        "status": "success",
        "result": {
            'request': data,
            'events': events
        }
    }
    return result


@app.post('/api/get_places/')
async def get_places(
        request: Request,
        token: str = Depends(verify_token),
    ):
    data = await request.json()
    cache_key = get_cache_key(data)
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    # task = celery_app.send_task(
    #     'davai_s_nami_bot.celery_tasks.get_places',
    #     args=[data],
    # )

    # return {'message': 'GET PLACES task added to queue', 'task_id': task.id}
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


@app.post("/api/get_place/{place_id}")
async def get_place_by_id(
        place_id: int,
        token: str = Depends(verify_token),
    ):

    cached_data = redis_client.get(f"place_{place_id}")
    if cached_data:
        return {"status": "success", "message": 'cached', "result": json.loads(cached_data)}

    data = {"ids": [place_id]}

    # task = celery_app.send_task(
    #     'davai_s_nami_bot.celery_tasks.get_places',
    #     args=[data],
    # )
    # redis_client.setex(task.id, 60 * 10, f"place_{place_id}")
    # return {'message': 'GET PLACE by ID added to queue', 'task_id': task.id}

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


@app.post('/api/get_exhibitions/')
async def get_exhibitions(request: Request, token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.get_exhibitions_celery',
    )
    return {'message': 'GET Exhibitions', 'task_id': task.id}


@app.get("/api/search/")
def search(query: str, limit: int = 10, token: str = Depends(verify_token)):
    events = crud.search_events_by_title(query, limit)
    if not events:
        places = crud.search_places_by_name(query, limit)
    else:
        places = []
    return {"events": events, "places": places}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
