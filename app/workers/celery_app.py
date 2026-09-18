"""
Celery app instance. Import `celery_app` wherever code needs to call
`.delay()`/`.apply_async()` on a task. Task modules live under
app/workers/tasks.py and are auto-discovered via `include=`.
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "caba",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,  # surface task exceptions immediately in eager/test mode
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # A stuck AI Brain call (model API hanging) shouldn't tie up a worker
    # slot indefinitely — acks_late + a time limit means a killed task's
    # message is redelivered to another worker rather than lost.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)