"""Celery task state: one read, a long-poll wait, and a change stream.

``TaskStatus.to_rest_dict`` is the body of GET /tasks/status/{id}; the gRPC
TaskUpdate carries the same fields.
"""
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from celery import states
from celery.result import AsyncResult

from .. import celery_app as celery_module
from .cache import json_default

POLL_INTERVAL_SEC = 0.1

# Returns True when the waiter should give up (client disconnected/cancelled).
StopCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class TaskStatus:
    task_id: str
    state: str  # Celery state: PENDING / STARTED / RETRY / SUCCESS / FAILURE / REVOKED
    result: Any = None
    error: Optional[str] = None

    @property
    def is_final(self) -> bool:
        return self.state in states.READY_STATES

    def to_rest_dict(self) -> dict:
        if self.state == states.SUCCESS:
            return {"status": "success", "result": self.result}
        if self.state == states.FAILURE:
            return {"status": "failure", "error": self.error}
        if self.state == states.RETRY:
            return {"status": self.state, "error": self.error}
        return {"status": self.state}


def get_task(task_id: str) -> TaskStatus:
    """Read the state once.

    On SUCCESS also fills the response cache a search endpoint registered under
    ``task_id`` (Redis ``task_id -> cache key``), as the REST status call does.
    """
    result = AsyncResult(task_id, app=celery_module.celery_app)
    state = result.state
    if state == states.SUCCESS:
        redis = celery_module.redis_client
        params = redis.get(task_id)
        if params:
            redis.setex(params, 60 * 60, json.dumps(result.result, default=json_default))
        return TaskStatus(task_id, state, result=result.result)
    if state in (states.FAILURE, states.RETRY):
        # result.info is the exception: final for FAILURE, the retry reason for RETRY.
        return TaskStatus(task_id, state, error=str(result.info))
    return TaskStatus(task_id, state)


async def wait_task(
    task_id: str,
    timeout: float,
    *,
    poll_interval: float = POLL_INTERVAL_SEC,
    should_stop: Optional[StopCheck] = None,
) -> TaskStatus:
    """Long-poll: the final state as soon as it is reached, else the state at ``timeout``."""
    deadline = time.monotonic() + timeout
    while True:
        status = get_task(task_id)
        if status.is_final or time.monotonic() >= deadline:
            return status
        if should_stop and await should_stop():
            return status
        await asyncio.sleep(min(poll_interval, max(deadline - time.monotonic(), 0)))


async def watch_task(
    task_id: str,
    *,
    poll_interval: float = POLL_INTERVAL_SEC,
    should_stop: Optional[StopCheck] = None,
) -> AsyncIterator[TaskStatus]:
    """Yield the current state, then each change, ending after a final state.

    No timeout of its own: the caller's deadline (gRPC) or ``should_stop`` ends it.
    A change is a new state or a new retry reason.
    """
    last = None
    while True:
        status = get_task(task_id)
        if (status.state, status.error) != last:
            last = (status.state, status.error)
            yield status
        if status.is_final:
            return
        if should_stop and await should_stop():
            return
        await asyncio.sleep(poll_interval)


def cancel_task(task_id: str) -> None:
    """Revoke without terminating: a running attempt finishes, retries do not start."""
    celery_module.celery_app.control.revoke(task_id)
