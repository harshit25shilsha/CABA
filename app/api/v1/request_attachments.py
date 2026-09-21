"""CA-provided guidance/reference/template attachments for a DocumentRequest."""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.v1.auth_dependencies import require_ca_or_sub_ca
from app.db.session import get_db
from app.models import DocumentRequest, RequestAttachment
from app.models.enums import AttachmentType
from app.schemas.request_attachment import RequestAttachmentRead
from app.services.storage.cloudinary_service import (
    CloudinaryStorageService,
    StorageUploadError,
    StorageUrlGenerationError,
)

router = APIRouter(prefix="/requests/{request_id}/attachments", tags=["request-attachments"])
storage_service = CloudinaryStorageService()


@router.post("", response_model=RequestAttachmentRead, status_code=201)
async def create_request_attachment(
    request_id: uuid.UUID,
    file: UploadFile,
    uploaded_by_user_id: uuid.UUID = Depends(require_ca_or_sub_ca),
    attachment_type: AttachmentType = Form(default=AttachmentType.OTHER),
    description: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> RequestAttachment:
    document_request = (
        await db.execute(select(DocumentRequest).where(DocumentRequest.id == request_id))
    ).scalar_one_or_none()
    if document_request is None:
        raise HTTPException(status_code=404, detail="Document request not found")

    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=422, detail="A filename is required for attachment")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Attachment cannot be empty")

    await file.seek(0)
    try:
        storage_result = await run_in_threadpool(
            storage_service.upload, file.file, filename=file.filename
        )
    except StorageUploadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    attachment = RequestAttachment(
        document_request_id=request_id,
        uploaded_by_user_id=uploaded_by_user_id,
        attachment_type=attachment_type,
        description=description,
        storage_provider="cloudinary",
        storage_public_id=storage_result.public_id,
        storage_resource_type=storage_result.resource_type,
        storage_format=storage_result.format or file.filename.rsplit(".", 1)[-1].lower(),
        # This is Cloudinary's provider URL, not a durable access URL because
        # the asset is private. Clients must use the signed-URL endpoint.
        storage_url=storage_result.source_url or "",
        original_filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        file_size_bytes=storage_result.bytes or len(file_bytes),
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return attachment


@router.get("", response_model=list[RequestAttachmentRead])
async def list_request_attachments(
    request_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[RequestAttachment]:
    request_exists = (
        await db.execute(select(DocumentRequest.id).where(DocumentRequest.id == request_id))
    ).scalar_one_or_none()
    if request_exists is None:
        raise HTTPException(status_code=404, detail="Document request not found")

    stmt = (
        select(RequestAttachment)
        .where(RequestAttachment.document_request_id == request_id)
        .order_by(RequestAttachment.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{attachment_id}/url")
async def get_request_attachment_signed_url(
    request_id: uuid.UUID,
    attachment_id: uuid.UUID,
    _user_id: uuid.UUID = Depends(require_ca_or_sub_ca),
    expires_in: int = Query(default=300, ge=1, le=3600),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | int]:
    stmt = select(RequestAttachment).where(
        RequestAttachment.id == attachment_id,
        RequestAttachment.document_request_id == request_id,
    )
    attachment = (await db.execute(stmt)).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found on this request")

    try:
        url = await run_in_threadpool(
            storage_service.generate_signed_url,
            attachment.storage_public_id,
            resource_type=attachment.storage_resource_type,
            file_format=attachment.storage_format,
            expires_in=expires_in,
        )
    except StorageUrlGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"url": url, "expires_in": expires_in}