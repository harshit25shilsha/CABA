"""
Assumes app.services.storage.cloudinary_service exposes:
    CloudinaryStorageService.upload(file, filename=...) -> UploadResult
matching the task brief given for the storage service (UploadResult has
.public_id, .secure_url, .bytes). If the delivered interface differs,
update the two call sites below — nothing else in this file depends on
storage internals.
"""
from io import BytesIO
import base64
import uuid
from app.services.storage.cloudinary_service import CloudinaryStorageService
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import get_db
from app.models import DocumentUpload, RequestedDocument
from app.models.enums import UploadStatus
from app.schemas.upload import UploadAccepted, UploadRead
from app.services.storage.cloudinary_service import CloudinaryStorageService
from ...workers.tasks import process_document_upload_task

router = APIRouter(tags=["uploads"])


@router.post(
    "/requests/{request_id}/documents/{requested_document_id}/uploads",
    response_model=UploadAccepted,
    status_code=202,
)
async def create_upload(
    request_id: uuid.UUID,
    requested_document_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> UploadAccepted:
    requested_doc = await _load_requested_document(request_id, requested_document_id, db)
    if requested_doc is None:
        raise HTTPException(status_code=404, detail="Requested document not found on this request")

    file_bytes = await file.read()
    mime_type = file.content_type or "application/octet-stream"

    # Cheap upfront rejection before spending a Cloudinary upload on an
    # obviously bad file — the deterministic rule engine re-checks this
    # later too (defense in depth), but there's no reason to store a file
    # we already know we'll reject.
    if mime_type not in settings.ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported file type: {mime_type}")
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=422, detail=f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB limit"
        )
    storage_service = CloudinaryStorageService()
    storage_result = storage_service.upload(
    BytesIO(file_bytes),
    filename=file.filename or "upload",
     )


    attempt_number = await _next_attempt_number(requested_document_id, db)

    upload = DocumentUpload(
        requested_document_id=requested_document_id,
        client_id=requested_doc.document_request.client_id,
        storage_provider="cloudinary",
        storage_public_id=storage_result.public_id,
        storage_url=storage_result.source_url,
        original_filename=file.filename or "upload",
        mime_type=mime_type,
        file_size_bytes=storage_result.bytes,
        upload_attempt_number=attempt_number,
        status=UploadStatus.UPLOADED,
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)

    # Same bytes that were just uploaded to Cloudinary are handed straight
    # to the task — no re-download from storage needed for this first run.
    async_result = process_document_upload_task.delay(
        str(upload.id), base64.b64encode(file_bytes).decode()
    )

    return UploadAccepted(upload=UploadRead.model_validate(upload), task_id=async_result.id)


@router.get(
    "/requests/{request_id}/documents/{requested_document_id}/uploads",
    response_model=list[UploadRead],
)
async def list_uploads(
    request_id: uuid.UUID, requested_document_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[DocumentUpload]:
    requested_doc = await _load_requested_document(request_id, requested_document_id, db)
    if requested_doc is None:
        raise HTTPException(status_code=404, detail="Requested document not found on this request")
    stmt = (
        select(DocumentUpload)
        .where(DocumentUpload.requested_document_id == requested_document_id)
        .order_by(DocumentUpload.upload_attempt_number)
    )
    return list((await db.execute(stmt)).scalars().all())


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


async def _next_attempt_number(requested_document_id: uuid.UUID, db: AsyncSession) -> int:
    stmt = select(func.count()).where(
        DocumentUpload.requested_document_id == requested_document_id
    )
    existing_count = (await db.execute(stmt)).scalar_one()
    return existing_count + 1
