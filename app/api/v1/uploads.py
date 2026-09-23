"""Client document uploads and access to their private Cloudinary assets.

Deliberately unauthenticated (no CA JWT dependency): per the Phase 1
design, clients never log in as Users — they interact via the link tied
to their DocumentRequest. Anyone with the request_id/requested_document_id
(effectively a bearer capability via unguessable UUIDs) can upload here,
same as they can already GET /requests/{id} with no auth.
"""

import base64
import io
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db
from app.models import AIProcessingResult, DocumentUpload, RequestedDocument
from app.models.enums import RequestStatus, UploadStatus
from app.schemas.document_upload import validate_uploaded_file
from app.schemas.upload import UploadAccepted, UploadRead, UploadRequestSummary, UploadResultRead
from app.services.pipeline.document_pipeline import _missing_mandatory_document_types_for_request
from app.services.storage.cloudinary_service import (
    StorageUploadError,
    StorageUrlGenerationError,
    get_storage_service,
)
from app.workers.tasks import process_document_upload_batch_task, process_document_upload_task

router = APIRouter(prefix="/client", tags=["client-uploads"])

# A request must be in one of these states for a client to upload against
# it — DRAFT means the CA hasn't published it yet (see POST
# /requests/{id}/publish), and CANCELLED/COMPLETED mean it's closed.
UPLOADABLE_REQUEST_STATUSES = {RequestStatus.OPEN, RequestStatus.IN_PROGRESS}


@router.post(
    "/requests/{request_id}/documents/uploads",
    response_model=list[UploadAccepted],
    status_code=202,
)
async def create_bulk_uploads(
    request_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    requested_document_ids: list[uuid.UUID] = Form(...),
    storage_service=Depends(get_storage_service),
    db: AsyncSession = Depends(get_db),
) -> list[UploadAccepted]:
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required.")
    if len(files) != len(requested_document_ids):
        raise HTTPException(
            status_code=422,
            detail="The number of files and requested_document_ids must match.",
        )
    if len(set(requested_document_ids)) != len(requested_document_ids):
        raise HTTPException(
            status_code=422,
            detail="requested_document_ids must be unique for a bulk upload.",
        )

    accepted: list[UploadAccepted] = []
    bulk_upload_payload: list[dict[str, str]] = []
    for file, requested_document_id in zip(files, requested_document_ids):
        requested_doc = await _load_requested_document(request_id, requested_document_id, db)
        if requested_doc is None:
            raise HTTPException(
                status_code=404,
                detail=f"Requested document {requested_document_id} not found on this request",
            )

        request_status = requested_doc.document_request.status
        if request_status not in UPLOADABLE_REQUEST_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"This request is not open for uploads (status: {request_status.value})",
            )

        filename, extension, content_type, file_size = await validate_uploaded_file(file)
        file_content = await file.read()
        await file.seek(0)

        try:
            storage_result = await run_in_threadpool(
                storage_service.upload, io.BytesIO(file_content), filename=filename
            )
        except StorageUploadError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        attempt_number = await _next_attempt_number(requested_document_id, db)
        upload = DocumentUpload(
            requested_document_id=requested_document_id,
            client_id=requested_doc.document_request.client_id,
            storage_provider="cloudinary",
            storage_public_id=storage_result.public_id,
            storage_resource_type=storage_result.resource_type,
            storage_format=storage_result.format or extension.lstrip("."),
            storage_url=storage_result.source_url or "",
            original_filename=filename,
            mime_type=content_type,
            file_size_bytes=storage_result.bytes or file_size,
            upload_attempt_number=attempt_number,
            status=UploadStatus.UPLOADED,
        )
        db.add(upload)
        await db.commit()
        await db.refresh(upload)

        bulk_upload_payload.append(
            {"upload_id": str(upload.id), "file_bytes_b64": base64.b64encode(file_content).decode()}
        )
        accepted.append(UploadAccepted(upload=UploadRead.model_validate(upload), task_id="pending"))

    if not bulk_upload_payload:
        return accepted

    batch_result = process_document_upload_batch_task.delay(str(request_id), bulk_upload_payload)
    for item in accepted:
        item.task_id = batch_result.id

    return accepted


@router.get(
    "/requests/{request_id}/uploads/summary",
    response_model=UploadRequestSummary,
)
async def get_request_upload_summary(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> UploadRequestSummary:
    requested_doc = await _load_requested_documents_for_request(request_id, db)
    if not requested_doc:
        raise HTTPException(status_code=404, detail="Request not found")

    missing_required_documents = await _missing_mandatory_document_types_for_request(db, request_id)
    stmt = (
        select(DocumentUpload)
        .join(RequestedDocument, DocumentUpload.requested_document_id == RequestedDocument.id)
        .where(RequestedDocument.document_request_id == request_id)
        .order_by(DocumentUpload.upload_attempt_number)
    )
    uploads = list((await db.execute(stmt)).scalars().all())
    results: list[UploadResultRead] = []
    for upload in uploads:
        explanation = await _latest_upload_explanation(db, upload.id)
        recommendation = explanation or _default_recommendation(upload.status)
        results.append(
            UploadResultRead(
                upload_id=upload.id,
                requested_document_id=upload.requested_document_id,
                status=upload.status,
                explanation=explanation,
                recommendation=recommendation,
                missing_required_documents=missing_required_documents,
                still_missing_required_documents=missing_required_documents,
            )
        )

    final_status = "completed" if not missing_required_documents else "in_progress"
    return UploadRequestSummary(
        request_id=request_id,
        final_status=final_status,
        missing_required_documents=missing_required_documents,
        still_missing_required_documents=missing_required_documents,
        results=results,
    )


@router.get(
    "/requests/{request_id}/results",
    response_model=UploadRequestSummary,
)
async def get_request_results(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> UploadRequestSummary:
    return await get_request_upload_summary(request_id=request_id, db=db)


async def _load_requested_document(
    request_id: uuid.UUID, requested_document_id: uuid.UUID, db: AsyncSession
) -> RequestedDocument | None:
    stmt = (
        select(RequestedDocument)
        .options(selectinload(RequestedDocument.document_request))
        .where(
            RequestedDocument.id == requested_document_id,
            RequestedDocument.document_request_id == request_id,
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _latest_upload_explanation(db: AsyncSession, upload_id: uuid.UUID) -> str | None:
    stmt = (
        select(AIProcessingResult)
        .where(AIProcessingResult.document_upload_id == upload_id)
        .order_by(AIProcessingResult.created_at.desc())
    )
    ai_results = list((await db.execute(stmt)).scalars().all())
    for ai_result in ai_results:
        explanation = ai_result.raw_output.get("explanation")
        if explanation:
            return str(explanation)
    upload = (await db.execute(select(DocumentUpload).where(DocumentUpload.id == upload_id))).scalar_one_or_none()
    if upload is None:
        return None
    if upload.status == UploadStatus.VALID:
        return "This document meets the requirement and has been accepted."
    if upload.status == UploadStatus.INVALID:
        return "This document does not meet the required criteria. Please re-upload a corrected version."
    if upload.status == UploadStatus.NEEDS_REVIEW:
        return "This document needs a manual review or a clearer upload before it can be accepted."
    return "This upload is still being processed."


async def _load_requested_documents_for_request(
    request_id: uuid.UUID, db: AsyncSession
) -> list[RequestedDocument]:
    stmt = select(RequestedDocument).where(RequestedDocument.document_request_id == request_id)
    return list((await db.execute(stmt)).scalars().all())


def _default_recommendation(status: UploadStatus) -> str:
    if status == UploadStatus.VALID:
        return "This document meets the requirement and has been accepted."
    if status == UploadStatus.INVALID:
        return "Please upload a clearer and complete document that matches the requested requirement."
    if status == UploadStatus.NEEDS_REVIEW:
        return "This document could not be verified automatically. Please upload a clearer version or request manual review."
    return "This upload is still being processed."


async def _next_attempt_number(requested_document_id: uuid.UUID, db: AsyncSession) -> int:
    stmt = select(func.count()).where(DocumentUpload.requested_document_id == requested_document_id)
    return (await db.execute(stmt)).scalar_one() + 1