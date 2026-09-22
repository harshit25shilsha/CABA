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

IMPORTANT — do not call .delay()/.apply_async() on this task from inside
async code (an async FastAPI route, an async test) with
CELERY_TASK_ALWAYS_EAGER=True. A real Celery worker runs tasks in a plain
sync context with no event loop of its own, so asyncio.run() inside this
task is correct there. But eager mode executes the task inline, and if
the caller is already inside a running event loop, asyncio.run() raises.
The tempting fix — falling back to a fresh event loop in a separate
thread — was tried and reverted: it caused this task's DB session to use
the shared async engine's connection pool from a second event loop,
which corrupted the pool for every other coroutine sharing it in the
same process (asyncpg connections are loop-affine and cannot safely be
used from more than one loop). Test this task's logic directly (call the
function, not through .delay(), as the existing tests do) or test the
upload endpoint by mocking .delay() and asserting it was called with the
right arguments — never both at once through eager mode from async code.

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

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services.ai_brain.factory import get_ai_brain
from app.services.pipeline.document_pipeline import (
    _missing_mandatory_document_types_for_request,
    process_document_upload,
)
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


@celery_app.task(
    name="process_document_upload_batch_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def process_document_upload_batch_task(self, request_id: str, upload_payloads: list[dict[str, str]]) -> dict:
    """Process a full bulk upload for one request and summarize the request state."""
    try:
        return asyncio.run(_run_batch(request_id, upload_payloads))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Batch pipeline task failed for request %s", request_id)
        raise self.retry(exc=exc)


def _new_task_session_factory() -> tuple[async_sessionmaker[AsyncSession], object]:
    """Each Celery task runs inside its own asyncio.run() loop.

    Reusing the module-level async engine across multiple task invocations in a
    long-lived worker process causes asyncpg to keep a stale loop reference and
    eventually throws "Event loop is closed"/"NoneType has no attribute send".
    Creating a fresh engine per task avoids that while keeping the rest of the
    app's FastAPI request flow unchanged.
    """
    engine = create_async_engine(
        settings.SQLALCHEMY_DATABASE_URI,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return session_factory, engine


async def _run(upload_id: str, file_bytes_b64: str) -> dict:
    file_bytes = base64.b64decode(file_bytes_b64)
    # get_ai_brain() is a per-process singleton — reused across task runs
    # within the same worker process rather than rebuilding the Groq/
    # vision API clients every call.
    brain = get_ai_brain()
    session_factory, engine = _new_task_session_factory()
    try:
        async with session_factory() as db:
            result = await process_document_upload(uuid.UUID(upload_id), file_bytes, db, brain)
    finally:
        await engine.dispose()
    return {
        "upload_id": str(result.upload_id),
        "final_status": result.final_status.value,
        "missing_required_documents": result.missing_required_documents,
        "still_missing_required_documents": result.missing_required_documents,
        "explanation": result.explanation,
    }


async def _run_batch(request_id: str, upload_payloads: list[dict[str, str]]) -> dict:
    brain = get_ai_brain()
    session_factory, engine = _new_task_session_factory()
    try:
        async with session_factory() as db:
            results: list[dict] = []
            for payload in upload_payloads:
                upload_id = payload["upload_id"]
                file_bytes = base64.b64decode(payload["file_bytes_b64"])
                result = await process_document_upload(uuid.UUID(upload_id), file_bytes, db, brain)
                results.append(
                    {
                        "upload_id": str(result.upload_id),
                        "final_status": result.final_status.value,
                        "missing_required_documents": result.missing_required_documents,
                        "still_missing_required_documents": result.missing_required_documents,
                        "explanation": result.explanation,
                    }
                )

            missing_required_documents = await _missing_mandatory_document_types_for_request(
                db, uuid.UUID(request_id)
            )
            overall_status = "completed" if not missing_required_documents else "in_progress"
            return {
                "request_id": request_id,
                "final_status": overall_status,
                "missing_required_documents": missing_required_documents,
                "still_missing_required_documents": missing_required_documents,
                "results": results,
            }
    finally:
        await engine.dispose()
