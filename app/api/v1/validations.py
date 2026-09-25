"""Java-facing endpoint that accepts validation work without blocking uploads."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.service_auth import require_java_service_key
from app.db.session import get_db
from app.models import ExternalValidationJob
from app.models.enums import ExternalValidationStatus
from app.schemas.external_validation import ExternalValidationAccepted, ExternalValidationCreate
from app.workers.tasks import process_external_validation_task

router = APIRouter(prefix="/validations", tags=["validations"])

_IDEMPOTENCY_WINDOW = timedelta(minutes=10)


@router.post("", response_model=ExternalValidationAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_external_validation(
    payload: ExternalValidationCreate,
    _authenticated: None = Depends(require_java_service_key),
    db: AsyncSession = Depends(get_db),
) -> ExternalValidationAccepted:
    """Persist then queue one Java document validation request.

    An advisory transaction lock serializes duplicate submissions for the same
    Java document. The worker lease independently makes duplicate task messages
    harmless after the request has committed.
    """

    await db.execute(select(func.pg_advisory_xact_lock(_advisory_lock_key(payload.external_ref))))
    cutoff = datetime.now(timezone.utc) - _IDEMPOTENCY_WINDOW
    existing = (
        await db.execute(
            select(ExternalValidationJob)
            .where(
                ExternalValidationJob.external_ref == payload.external_ref,
                ExternalValidationJob.created_at >= cutoff,
            )
            .order_by(desc(ExternalValidationJob.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing is not None:
        await db.commit()
        return ExternalValidationAccepted(upload_id=existing.upload_id)

    job = ExternalValidationJob(
        upload_id=f"aib_{uuid.uuid4().hex}",
        external_ref=payload.external_ref,
        file_url=payload.file_url,
        mime_type=payload.mime_type,
        requirement_text=payload.requirement_text,
        client_profile=payload.client_profile,
        status=ExternalValidationStatus.QUEUED,
    )
    db.add(job)
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Unable to queue validation") from exc

    await _enqueue_or_report_failure(job, db)
    return ExternalValidationAccepted(upload_id=job.upload_id)


async def _enqueue_or_report_failure(job: ExternalValidationJob, db: AsyncSession) -> None:
    try:
        process_external_validation_task.delay(str(job.id))
    except Exception as exc:  # noqa: BLE001 - Java receives a retryable response when Redis is unavailable.
        job.processing_error = f"Unable to enqueue validation task: {exc}"
        job.status = ExternalValidationStatus.QUEUED
        await db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Unable to queue validation") from exc


def _advisory_lock_key(external_ref: str) -> int:
    """Stable signed 64-bit PostgreSQL advisory-lock key for one external ref."""

    digest = hashlib.blake2b(external_ref.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)
