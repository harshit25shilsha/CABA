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
    storage_resource_type: str
    storage_format: str
    status: UploadStatus
    created_at: datetime


class UploadAccepted(BaseModel):
    """Returned immediately on upload — processing happens async via Celery,
    so this reports UPLOADED/queued, not the eventual VALID/INVALID/NEEDS_REVIEW."""

    upload: UploadRead
    task_id: str


class UploadResultRead(BaseModel):
    """Final post-processing result for one uploaded document."""

    upload_id: uuid.UUID
    requested_document_id: uuid.UUID
    status: UploadStatus
    explanation: str | None = None
    recommendation: str | None = None
    missing_required_documents: list[str] = []
    still_missing_required_documents: list[str] = []


class UploadRequestSummary(BaseModel):
    """Request-level summary used by the client after a bulk upload."""

    request_id: uuid.UUID
    final_status: str
    missing_required_documents: list[str] = []
    still_missing_required_documents: list[str] = []
    results: list[UploadResultRead] = []
