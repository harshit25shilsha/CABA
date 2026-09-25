"""
Celery app instance. Import `celery_app` wherever code needs to call
`.delay()`/`.apply_async()` on a task. Task modules live under
app/workers/tasks.py and are auto-discovered via `include=`.
"""

from celery import Celery
from kombu import Queue
from app.core.config import settings

celery_app = Celery(
    "caba",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,     
    broker_connection_retry_on_startup=True,  
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    
    task_queues=(
        Queue("validation"),
        Queue("webhook"),
    ),

    
    task_routes={
        "process_external_validation_task": {
            "queue": "validation",
        },
        "send_verdict_webhook_task": {
            "queue": "webhook",
        },
    },

    task_annotations={
    "process_external_validation_task": {
        "rate_limit": settings.VALIDATION_TASK_RATE_LIMIT,
    },
 },
)