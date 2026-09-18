import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AttachmentType


class RequestAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_request_id: uuid.UUID
    attachment_type: AttachmentType
    description: str | None
    original_filename: str
    mime_type: str
    file_size_bytes: int
    storage_resource_type: str
    storage_format: str
    storage_url: str
    created_at: datetime
