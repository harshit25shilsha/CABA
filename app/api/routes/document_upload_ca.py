from __future__ import annotations
import uuid
from pathlib import Path
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
import app.models.document_request
from app.models.enums import (
    RequestStatus,
    RequirementStatus,
    UploadStatus,
)
from app.models.upload import DocumentUpload
from app.schemas.document_upload import DocumentUploadResponse
from app.services.storage.cloudinary_service import (
    CloudinaryStorageService,
    StorageUploadError,
)
import app.schemas.document_upload
router = APIRouter(
    prefix="/document-uploads",
    tags=["CA Document Upload"],
)
storage_service = CloudinaryStorageService()

@router.post(
    "/ca",
    status_code=status.HTTP_201_CREATED,
    response_model=app.schemas.document_upload.DocumentUploadResponse,
)
async def create_ca_document_request(
    request: Request,
    client_id: uuid.UUID = Form(...),
    service_id: str | None = Form(None),
    sub_service_id: str | None = Form(None),
    description: str | None = Form(None),
    document_type: str = Form(...),
    is_mandatory: bool = Form(True),
    display_order: int = Form(0),
    requirement_text: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    created_by_user_id = request.state.user_id  
    service_uuid = app.schemas.document_upload.parse_optional_uuid(
        service_id,
        "service_id",
    )
    sub_service_uuid = app.schemas.document_upload.parse_optional_uuid(
        sub_service_id,
        "sub_service_id",
    )    
    document_type = document_type.strip()
    if not document_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_type cannot be empty.",
        )
    if len(document_type) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_type cannot exceed 100 characters.",
        )    
    requirement_text = requirement_text.strip()

    if not requirement_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="requirement_text cannot be empty.",
        )
   
    if description is not None:
        description = description.strip()

        if not description:
            description = None
   
    if display_order < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="display_order cannot be negative.",
        )
    
    (
        filename,
        _extension,
        content_type,
        file_size,
    ) = await app.schemas.document_upload.validate_uploaded_file(file)
   
    document_request = app.models.document_request.DocumentRequest(
        client_id=client_id,
        created_by_user_id=created_by_user_id,
        service_id=service_uuid,
        sub_service_id=sub_service_uuid,
        description=description,
        status=RequestStatus.DRAFT,
    )
    db.add(document_request)
    await db.flush()   
    requested_document = app.models.document_request.RequestedDocument(
        document_request_id=document_request.id,
        document_type=document_type,
        is_mandatory=is_mandatory,
        display_order=display_order,
    )
    db.add(requested_document)
    await db.flush()
   
    requirement = app.models.document_request.Requirement(
        requested_document_id=requested_document.id,
        raw_text=requirement_text,
        status=RequirementStatus.PENDING_INTERPRETATION,
    )
    db.add(requirement)

    try:
        upload_result = storage_service.upload(
            file.file,
            filename=filename,
        )

    except StorageUploadError as exc:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cloudinary upload failed.",
        ) from exc
   
    if not upload_result.source_url:
        await db.rollback()

        try:
            storage_service.delete(
                upload_result.public_id,
                resource_type=upload_result.resource_type,
            )
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Cloudinary upload succeeded but "
                "no URL was returned."
            ),
        )
    
    document_upload = DocumentUpload(
        requested_document_id=requested_document.id,
        client_id=client_id,
        storage_provider="cloudinary",
        storage_public_id=upload_result.public_id,
        storage_url=upload_result.source_url,
        original_filename=filename,
        mime_type=content_type,
        file_size_bytes=file_size,
        upload_attempt_number=1,
        status=UploadStatus.UPLOADED,
    )

    db.add(document_upload)
    
    try:
        await db.commit()

        await db.refresh(
            document_upload
        )

    except Exception as exc:
        await db.rollback()

        try:
            storage_service.delete(
                upload_result.public_id,
                resource_type=upload_result.resource_type,
            )
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save document upload.",
        ) from exc

    return document_upload