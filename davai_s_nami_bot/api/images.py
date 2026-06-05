from fastapi import APIRouter, Depends

from ..celery_app import celery_app
from .dependencies import verify_token
from .schemas import UploadImageRequest, UploadEventImagesRequest, TaskResponse

router = APIRouter(
    prefix="/images",
    tags=["Images"],
    dependencies=[Depends(verify_token)],
)


@router.post("/upload-to-s3/", response_model=TaskResponse,
              summary="Upload an image to S3",
              description="Upload a single image by URL to AWS S3.")
async def upload_image_to_s3(body: UploadImageRequest):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.upload_image_to_s3',
        args=[body.img_url],
    )
    return TaskResponse(message='Task upload images to s3 to queue', task_id=task.id)


@router.post("/upload-event-images-to-s3/", response_model=TaskResponse,
              summary="Upload event images to S3",
              description="Bulk upload of event images to AWS S3 by a list of IDs.")
async def upload_event_images_to_s3(body: UploadEventImagesRequest):
    task = celery_app.send_task(
        'davai_s_nami_bot.celery_tasks.upload_event_images_to_s3',
        args=[body.event_ids],
    )
    return TaskResponse(message='Task upload event images to s3 to queue', task_id=task.id)
