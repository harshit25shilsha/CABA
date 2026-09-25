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
from app.services.external_validation.webhook import (
    JavaWebhookConfigurationError,
    JavaWebhookDeliveryError,
    post_signed_verdict,
)
from app.services.pipeline.external_validation_pipeline import process_external_validation
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_WEBHOOK_RETRY_DELAYS_SECONDS = (5, 30, 300)


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
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
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
            # A broker failure after pipeline commit is retried by this task.
            # Do not run the AI stages again; only re-dispatch the durable
            # callback job that is already waiting in the database.
            existing = await db.get(ExternalValidationJob, job_id)
            if existing is None:
                raise ValueError(f"ExternalValidationJob {job_id} not found")
            if existing.status == ExternalValidationStatus.DELIVERY_PENDING:
                deliver_external_validation_verdict_task.delay(str(existing.id))
                return {"upload_id": existing.upload_id, "status": "delivery_queued"}

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
            job.status = ExternalValidationStatus.DELIVERY_PENDING
            await db.commit()

            # The result is durable before this publish. If Redis is briefly
            # unavailable, the retry path above dispatches only this callback.
            deliver_external_validation_verdict_task.delay(str(job.id))

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


@celery_app.task(
    name="deliver_external_validation_verdict_task",
    bind=True,
    max_retries=len(_WEBHOOK_RETRY_DELAYS_SECONDS),
)
def deliver_external_validation_verdict_task(self, job_id: str) -> dict:
    """Deliver a persisted verdict; retries never rerun AI processing."""

    try:
        outcome = asyncio.run(_deliver_external_validation_verdict(uuid.UUID(job_id)))
    except JavaWebhookConfigurationError as exc:
        logger.error("Java webhook is not configured for job %s: %s", job_id, exc)
        asyncio.run(_mark_delivery_failed(uuid.UUID(job_id), str(exc)))
        return {"job_id": job_id, "delivery_status": "configuration_error"}

    if outcome.retry_after_seconds is not None:
        raise self.retry(
            exc=JavaWebhookDeliveryError(outcome.error or "Java webhook delivery failed"),
            countdown=outcome.retry_after_seconds,
        )
    return {
        "job_id": job_id,
        "delivery_status": outcome.delivery_status,
        "callback_attempts": outcome.callback_attempts,
    }


class _DeliveryOutcome:
    def __init__(
        self,
        delivery_status: str,
        callback_attempts: int,
        retry_after_seconds: int | None = None,
        error: str | None = None,
    ) -> None:
        self.delivery_status = delivery_status
        self.callback_attempts = callback_attempts
        self.retry_after_seconds = retry_after_seconds
        self.error = error


async def _deliver_external_validation_verdict(job_id: uuid.UUID) -> _DeliveryOutcome:
    session_factory, engine = _new_task_session_factory()
    try:
        async with session_factory() as db:
            job = (
                await db.execute(
                    select(ExternalValidationJob)
                    .where(ExternalValidationJob.id == job_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is None:
                raise ValueError(f"ExternalValidationJob {job_id} not found")
            if job.callback_delivered_at is not None:
                return _DeliveryOutcome("already_delivered", job.callback_attempts)
            if job.status == ExternalValidationStatus.DELIVERY_FAILED:
                return _DeliveryOutcome("delivery_failed", job.callback_attempts)

            try:
                await post_signed_verdict(job)
            except JavaWebhookConfigurationError:
                raise
            except JavaWebhookDeliveryError as exc:
                job.callback_attempts += 1
                job.last_callback_error = str(exc)
                if job.callback_attempts <= len(_WEBHOOK_RETRY_DELAYS_SECONDS):
                    retry_after = _WEBHOOK_RETRY_DELAYS_SECONDS[job.callback_attempts - 1]
                    job.status = ExternalValidationStatus.DELIVERY_PENDING
                    job.callback_next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
                    await db.commit()
                    return _DeliveryOutcome(
                        "retry_scheduled",
                        job.callback_attempts,
                        retry_after_seconds=retry_after,
                        error=str(exc),
                    )

                job.status = ExternalValidationStatus.DELIVERY_FAILED
                job.callback_next_attempt_at = None
                await db.commit()
                return _DeliveryOutcome("delivery_failed", job.callback_attempts, error=str(exc))

            job.callback_attempts += 1
            job.callback_delivered_at = datetime.now(timezone.utc)
            job.callback_next_attempt_at = None
            job.last_callback_error = None
            job.status = ExternalValidationStatus.COMPLETED
            await db.commit()
            return _DeliveryOutcome("delivered", job.callback_attempts)
    finally:
        await engine.dispose()


async def _mark_delivery_failed(job_id: uuid.UUID, error: str) -> None:
    """Persist non-retryable configuration errors for operational repair."""

    session_factory, engine = _new_task_session_factory()
    try:
        async with session_factory() as db:
            job = (
                await db.execute(
                    select(ExternalValidationJob)
                    .where(ExternalValidationJob.id == job_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is not None and job.callback_delivered_at is None:
                job.status = ExternalValidationStatus.DELIVERY_FAILED
                job.callback_next_attempt_at = None
                job.last_callback_error = error
                await db.commit()
    finally:
        await engine.dispose()
