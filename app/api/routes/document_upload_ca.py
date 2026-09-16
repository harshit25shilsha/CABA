from __future__ import annotations
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.session import get_db
from app.models.document_request import (
    DocumentRequest,
    RequestedDocument,
    Requirement,
)
from app.models.enums import (
    RequestStatus,
    RequirementStatus,
    UploadStatus,
)
from app.models.upload import DocumentUpload
from app.services.storage.cloudinary_service import (
    CloudinaryStorageService,
    StorageUploadError,
)
router = APIRouter(
    prefix="/document-uploads",
    tags=["CA Document Upload"],
)

storage_service = CloudinaryStorageService()

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".jpg",
    ".jpeg",
    ".png",
}

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}

MAX_FILE_SIZE = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

class DocumentUploadResponse(BaseModel):
    """
    Response schema matching the document_uploads table.
    """

    requested_document_id: uuid.UUID

    client_id: uuid.UUID

    storage_provider: Literal["cloudinary"]

    storage_public_id: str = Field(
        ...,
        min_length=1,
        max_length=500,
    )

    storage_url: AnyHttpUrl

    original_filename: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    mime_type: str = Field(
        ...,
        min_length=1,
        max_length=150,
    )

    file_size_bytes: int = Field(
        ...,
        gt=0,
    )

    upload_attempt_number: int = Field(
        ...,
        ge=1,
    )

    status: UploadStatus

    id: uuid.UUID

    created_at: datetime

    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )

def validate_filename(
    filename: str | None,
) -> str:

    if filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required.",
        )

    filename = filename.strip()

    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename cannot be empty.",
        )

    if len(filename) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename cannot exceed 255 characters.",
        )

    if Path(filename).name != filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    return filename

def validate_extension(
    filename: str,
) -> str:

    extension = Path(filename).suffix.lower()

    if not extension:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension is required.",
        )

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file extension '{extension}'. "
                f"Allowed extensions: "
                f"{sorted(ALLOWED_EXTENSIONS)}."
            ),
        )

    return extension

def validate_content_type(
    content_type: str | None,
) -> str:

    if not content_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content type is required.",
        )

    content_type = content_type.strip().lower()

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported content type '{content_type}'. "
                f"Allowed types: "
                f"{sorted(ALLOWED_CONTENT_TYPES)}."
            ),
        )

    return content_type

def validate_file_type_match(
    extension: str,
    content_type: str,
) -> None:

    valid_combinations = {
        ".pdf": {
            "application/pdf",
        },
        ".docx": {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
        ".jpg": {
            "image/jpeg",
        },
        ".jpeg": {
            "image/jpeg",
        },
        ".png": {
            "image/png",
        },
    }

    allowed_content_types = valid_combinations.get(
        extension,
        set(),
    )

    if content_type not in allowed_content_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File extension '{extension}' does not match "
                f"content type '{content_type}'."
            ),
        )

def validate_file_signature(
    file_content: bytes,
    extension: str,
) -> None:

    valid_signatures = {
        ".pdf": (
            b"%PDF-",
        ),
        ".docx": (
            b"PK\x03\x04",
        ),
        ".jpg": (
            b"\xff\xd8\xff",
        ),
        ".jpeg": (
            b"\xff\xd8\xff",
        ),
        ".png": (
            b"\x89PNG\r\n\x1a\n",
        ),
    }

    signatures = valid_signatures.get(
        extension,
        (),
    )

    if not signatures:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type.",
        )

    if not any(
        file_content.startswith(signature)
        for signature in signatures
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "File content does not match "
                "the file extension."
            ),
        )

def parse_optional_uuid(
    value: str | None,
    field_name: str,
 ) -> uuid.UUID | None:
    if value is None or not value.strip():
        return None

    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be a valid UUID",
        )

@router.post(
    "/ca",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentUploadResponse,
)
async def create_ca_document_request(
    client_id: uuid.UUID = Form(...),
    created_by_user_id: uuid.UUID = Form(...),
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

    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id is required.",
        )

    if not created_by_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="created_by_user_id is required.",
        )

    service_uuid = parse_optional_uuid(service_id, "service_id")
    sub_service_uuid = parse_optional_uuid(
        sub_service_id,
        "sub_service_id",
    )

    if not document_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_type is required.",
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
            detail=(
                "document_type cannot exceed "
                "100 characters."
            ),
        )

    if not requirement_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="requirement_text is required.",
        )

    requirement_text = requirement_text.strip()

    if not requirement_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "requirement_text cannot be empty."
            ),
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

    filename = validate_filename(
        file.filename
    )

    extension = validate_extension(
        filename
    )

    content_type = validate_content_type(
        file.content_type
    )
    validate_file_type_match(
        extension,
        content_type,
    )
    try:

        file_content = await file.read(
            MAX_FILE_SIZE + 1
        )

    except Exception as exc:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to read uploaded file.",
        ) from exc

    if not file_content:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file cannot be empty.",
        )

    file_size = len(file_content)

    if file_size > MAX_FILE_SIZE:

        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File size cannot exceed "
                f"{settings.MAX_UPLOAD_SIZE_MB} MB."
            ),
        )

    validate_file_signature(
        file_content,
        extension,
    )
    await file.seek(0)
    document_request = DocumentRequest(
    client_id=client_id,
    created_by_user_id=created_by_user_id,
    service_id=service_uuid,
    sub_service_id=sub_service_uuid,
    description=description,
    status=RequestStatus.DRAFT,
)

    db.add(document_request)
    await db.flush()
    requested_document = RequestedDocument(
        document_request_id=document_request.id,
        document_type=document_type,
        is_mandatory=is_mandatory,
        display_order=display_order,
    )

    db.add(requested_document)

    await db.flush()

    requirement = Requirement(
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
            detail=(
                "Failed to save document upload."
            ),
        ) from exc

    return document_upload
