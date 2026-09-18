"""Client document uploads and access to their private Cloudinary assets."""

import base64
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.db.session import get_db
from app.models import DocumentUpload, RequestedDocument
from app.models.enums import UploadStatus
from app.schemas.upload import UploadAccepted, UploadRead
from app.services.storage.cloudinary_service import (
    CloudinaryStorageService,
    StorageUploadError,
    StorageUrlGenerationError,
)
from app.workers.tasks import process_document_upload_task

router = APIRouter(tags=["uploads"])
storage_service = CloudinaryStorageService()


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

    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=422, detail="A filename is required for upload")

    file_bytes = await file.read()
    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in settings.ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported file type: {mime_type}")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(status_code=422, detail=f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB limit")
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Upload cannot be empty")

    await file.seek(0)
    try:
        storage_result = await run_in_threadpool(
            storage_service.upload, file.file, filename=file.filename
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
        storage_format=storage_result.format or file.filename.rsplit(".", 1)[-1].lower(),
        # Private asset source URL; use the signed-URL endpoint for access.
        storage_url=storage_result.source_url or "",
        original_filename=file.filename,
        mime_type=mime_type,
        file_size_bytes=storage_result.bytes or len(file_bytes),
        upload_attempt_number=attempt_number,
        status=UploadStatus.UPLOADED,
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)

    async_result = process_document_upload_task.delay(
        str(upload.id), base64.b64encode(file_bytes).decode()
    )
    return UploadAccepted(upload=UploadRead.model_validate(upload), task_id=async_result.id)


@router.get(
    "/requests/{request_id}/documents/{requested_document_id}/uploads",
    response_model=list[UploadRead],
)
async def list_uploads(
    request_id: uuid.UUID,
    requested_document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentUpload]:
    requested_doc = await _load_requested_document(request_id, requested_document_id, db)
    if requested_doc is None:
        raise HTTPException(status_code=404, detail="Requested document not found on this request")
    stmt = select(DocumentUpload).where(
        DocumentUpload.requested_document_id == requested_document_id
    ).order_by(DocumentUpload.upload_attempt_number)
    return list((await db.execute(stmt)).scalars().all())


@router.get(
    "/requests/{request_id}/documents/{requested_document_id}/uploads/{upload_id}/url",
)
async def get_upload_signed_url(
    request_id: uuid.UUID,
    requested_document_id: uuid.UUID,
    upload_id: uuid.UUID,
    expires_in: int = Query(default=300, ge=1, le=3600),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | int]:
    stmt = (
        select(DocumentUpload)
        .join(RequestedDocument, DocumentUpload.requested_document_id == RequestedDocument.id)
        .where(
            DocumentUpload.id == upload_id,
            DocumentUpload.requested_document_id == requested_document_id,
            RequestedDocument.document_request_id == request_id,
        )
    )
    upload = (await db.execute(stmt)).scalar_one_or_none()
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found on this request")

    try:
        url = await run_in_threadpool(
            storage_service.generate_signed_url,
            upload.storage_public_id,
            resource_type=upload.storage_resource_type,
            file_format=upload.storage_format,
            expires_in=expires_in,
        )
    except StorageUrlGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"url": url, "expires_in": expires_in}


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
    stmt = select(func.count()).where(DocumentUpload.requested_document_id == requested_document_id)
    return (await db.execute(stmt)).scalar_one() + 1
