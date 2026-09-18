from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import AnyHttpUrl, BaseModel, ConfigDict , Field
from app.models.enums import UploadStatus

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
