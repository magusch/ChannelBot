import os

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from davai_s_nami_bot.celery_app import celery_app
from celery.result import AsyncResult
from datetime import datetime

app = FastAPI()
security = HTTPBearer()

class UpdatePostingRequest(BaseModel):
    event_id: int
    scheduled_time: datetime


API_TOKEN = os.environ.get('API_TOKEN', 'your-secure-api-token')


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    if token == API_TOKEN:
        return API_TOKEN
    else:
        raise HTTPException(status_code=403, detail="Invalid token")

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
    result = AsyncResult(task_id, app=celery_app)
    if result.state == 'SUCCESS':
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
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.get_posted_events',
        args=[data],
    )
    return {'message': 'GET EVENTS', 'task_id': task.id}


@app.post('/api/get_exhibitions/')
async def get_exhibitions(request: Request, token: str = Depends(verify_token)):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.get_exhibitions_celery',
    )
    return {'message': 'GET Exhibitions', 'task_id': task.id}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
