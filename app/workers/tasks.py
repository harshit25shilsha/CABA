"""
Celery tasks. A worker process is separate from the FastAPI app, so
nothing from a request's dependency injection carries over — each task
run builds its own DB session directly from app.db.session.

Registered via @celery_app.task, not @shared_task: this project has a
single Celery app, and shared_task resolves against whichever app is
"current" at call time — which only reliably matches celery_app inside
an actual running worker process. Called directly (as in tests, or from
a script before any worker context exists), shared_task silently falls
back to Celery's default app (default broker: amqp://), not the Redis
broker configured here. Binding directly to celery_app avoids that.

file_bytes is passed base64-encoded because Celery's JSON serializer
can't carry raw bytes. For large files this bloats the broker message;
once the storage service can be queried by public_id, switch this task
to fetching bytes itself inside the task rather than receiving them —
kept base64 for now since Cloudinary wiring isn't done yet, and the
pipeline (process_document_upload) already takes file_bytes as a plain
parameter regardless of where they came from.
"""

import asyncio
import base64
import logging
import uuid

from app.db.session import AsyncSessionLocal
from app.services.ai_brain.factory import get_ai_brain
from app.services.pipeline.document_pipeline import process_document_upload
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="process_document_upload_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def process_document_upload_task(self, upload_id: str, file_bytes_b64: str) -> dict:
    try:
        return asyncio.run(_run(upload_id, file_bytes_b64))
    except Exception as exc:  # noqa: BLE001 — any failure here is worth a
        # retry (transient DB/network blip) rather than immediately
        # dropping the task; the pipeline's own processors already catch
        # and report their own model/API failures as NEEDS_REVIEW-routable
        # results, so an exception escaping this far means something more
        # fundamental broke (DB connection, task/serialization bug, etc).
        logger.exception("Pipeline task failed for upload %s", upload_id)
        raise self.retry(exc=exc)


async def _run(upload_id: str, file_bytes_b64: str) -> dict:
    file_bytes = base64.b64decode(file_bytes_b64)
    # get_ai_brain() is a per-process singleton — reused across task runs
    # within the same worker process rather than rebuilding the Groq/
    # vision API clients every call.
    brain = get_ai_brain()
    async with AsyncSessionLocal() as db:
        result = await process_document_upload(uuid.UUID(upload_id), file_bytes, db, brain)
    return {
        "upload_id": str(result.upload_id),
        "final_status": result.final_status.value,
        "explanation": result.explanation,
    }