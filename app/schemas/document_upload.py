from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import AnyHttpUrl, BaseModel, ConfigDict , Field
from app.models.enums import UploadStatus
from pathlib import Path
from fastapi import HTTPException, UploadFile, status
from app.core.config import settings
from dataclasses import dataclass
from enum import Enum

class DocumentUploadResponse(BaseModel):
    """
    API response returned after a document upload.
    """
    id: uuid.UUID
    requested_document_id: uuid.UUID
    client_id: uuid.UUID
    storage_provider: str = Field(
        ...,
        min_length=1,
        max_length=50
    )
    storage_public_id: str = Field(
        ...,
        min_length=1,
        max_length=500
    )
    storage_url: AnyHttpUrl
    original_filename: str = Field(
        ...,
        min_length=1,
        max_length=255
    )
    mime_type: str = Field(
        ...,
        min_length=1,
        max_length=150
    )
    file_size_bytes:int = Field(
        ...,
        ge=0
    )
    upload_attempt_number: int = Field(
        ...,
        ge=1
    )
    status: UploadStatus
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(
        from_attributes=True
    )
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

async def validate_uploaded_file(file: UploadFile):
    filename = validate_filename(file.filename)
    extension = validate_extension(filename)
    content_type = validate_content_type(file.content_type)

    validate_file_type_match(
        extension,
        content_type,
    )

    try:
        file_content = await file.read(MAX_FILE_SIZE + 1)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Unable to read uploaded file.",
        ) from exc

    if not file_content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file cannot be empty.",
        )
    file_size = len(file_content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size exceeded.",
        )
    validate_file_signature(
        file_content,
        extension,
    )
    await file.seek(0)
    return filename, extension, content_type, file_size



#Cloudnary Lifecycle 

# This enum defines all the possible storage locations
# where a document can be stored in our application.
class StorageStage(str, Enum):
    TEMP = "temp"
    PERMANENT = "permanent"
    QUARANTINE = "quarantine"
    REVIEW = "review"

# This class stores the information returned after uploading a file.
# frozen=True means the result cannot be changed after it is created.

@dataclass(frozen=True)
class UploadResult:
    public_id: str
    resource_type: str
    format: str|None
    bytes: int|None
    source_url: str|None
    stage: StorageStage

# This class stores the information returned after moving a file
# from one storage stage to another.    

@dataclass(frozen=True)
class MoveResult:
    old_public_id: str
    public_id: str
    resource_type: str
    stage: StorageStage

# This class stores the information returned after deleting a file.
@dataclass(frozen=True)
class DeleteResult:
    public_id: str
    resource_type: str
    deleted: bool        
