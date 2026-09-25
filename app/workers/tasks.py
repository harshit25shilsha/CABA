"""Celery tasks for Java-originated document validations."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models import ExternalValidationJob
from app.models.enums import ExternalValidationStatus
from app.services.ai_brain.factory import get_ai_brain
from app.services.external_validation.file_download import download_external_document
from app.services.pipeline.external_validation_pipeline import process_external_validation
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="process_external_validation_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def process_external_validation_task(self, job_id: str) -> dict:
    try:
        return asyncio.run(_run_external_validation(uuid.UUID(job_id)))
    except Exception as exc:  # noqa: BLE001 - DB, download, and provider failures are retryable.
        logger.exception("External validation task failed for job %s", job_id)
        raise self.retry(exc=exc)


def _new_task_session_factory() -> tuple[async_sessionmaker[AsyncSession], object]:
    """Use a fresh async engine for each asyncio.run() worker invocation."""

    engine = create_async_engine(
        settings.SQLALCHEMY_DATABASE_URI,
        echo=settings.DB_ECHO,
        # pool_size=settings.DB_POOL_SIZE,
        # max_overflow=settings.DB_MAX_OVERFLOW,
        pool_size=1,
        max_overflow=0,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )
    return (
        async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        ),
        engine,
    )


async def _run_external_validation(job_id: uuid.UUID) -> dict:
    session_factory, engine = _new_task_session_factory()
    try:
        async with session_factory() as db:
            job = await _claim_job(db, job_id)
            if job is None:
                return {"job_id": str(job_id), "status": "already_processing_or_completed"}

            try:
                downloaded = await download_external_document(job.file_url, job.mime_type)
                result = await process_external_validation(
                    job,
                    downloaded.content,
                    downloaded.size_bytes,
                    get_ai_brain(),
                )
            except Exception as exc:
                job.status = ExternalValidationStatus.QUEUED
                job.processing_lease_until = None
                job.processing_error = str(exc)
                await db.commit()
                raise

            job.file_size_bytes = downloaded.size_bytes
            job.verdict = result.verdict
            job.confidence = result.confidence
            job.explanation = result.explanation
            job.checks = result.checks
            job.processing_error = result.failure_reason
            job.processing_lease_until = None
            job.status = ExternalValidationStatus.COMPLETED
            await db.commit()

            return {
                "upload_id": job.upload_id,
                "verdict": result.verdict.value,
                "confidence": result.confidence,
                "explanation": result.explanation,
                "checks": result.checks,
            }
    finally:
        await engine.dispose()


async def _claim_job(db: AsyncSession, job_id: uuid.UUID) -> ExternalValidationJob | None:
    """Atomically acquire a queued or expired job lease for one worker."""

    job = (
        await db.execute(
            select(ExternalValidationJob)
            .where(ExternalValidationJob.id == job_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise ValueError(f"ExternalValidationJob {job_id} not found")

    now = datetime.now(timezone.utc)
    terminal_statuses = {
        ExternalValidationStatus.COMPLETED,
        ExternalValidationStatus.DELIVERY_PENDING,
        ExternalValidationStatus.DELIVERY_FAILED,
    }
    if job.status in terminal_statuses:
        return None
    if (
        job.status == ExternalValidationStatus.PROCESSING
        and job.processing_lease_until is not None
        and job.processing_lease_until > now
    ):
        return None

    job.status = ExternalValidationStatus.PROCESSING
    job.processing_error = None
    job.processing_lease_until = now + timedelta(seconds=settings.PROCESSING_LEASE_SECONDS)
    await db.commit()
    return job
