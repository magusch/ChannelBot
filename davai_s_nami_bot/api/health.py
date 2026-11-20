from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from ..services import health
from .dependencies import verify_health_token

router = APIRouter(prefix="/health", tags=["Health"])


@router.get(
    "/report",
    summary="Morning health report",
    description=(
        "DB/Redis/Celery liveness, today's nightly tasks, what was scraped, "
        "what is queued for today and what went out yesterday. `status` is "
        "`ok`/`warn`/`fail` from `problems` (volume-independent breakage); "
        "`notes` compare against the city's own last 28 days and do not change "
        "`status`. Always 200 so the body is readable. City: `?city=`. "
        "Auth: `Bearer <HEALTH_TOKEN>`, not the API token."
    ),
)
async def health_report(token: str = Depends(verify_health_token)):
    return await run_in_threadpool(health.build_report)
