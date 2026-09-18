import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import UploadStatus


class UploadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requested_document_id: uuid.UUID
    original_filename: str
    mime_type: str
    file_size_bytes: int
    status: UploadStatus
    created_at: datetime


class UploadAccepted(BaseModel):
    """Returned immediately on upload — processing happens async via Celery,
    so this reports UPLOADED/queued, not the eventual VALID/INVALID/NEEDS_REVIEW."""

    upload: UploadRead
    task_id: str
