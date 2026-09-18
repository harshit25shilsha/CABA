import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import RequestStatus, RequirementStatus
# from app.schemas.request_attachment import RequestAttachmentRead


class RequestedDocumentCreate(BaseModel):
    document_type: str
    is_mandatory: bool = True
    display_order: int = 0
    # The CA's freeform natural-language requirement — this is what
    # UNDERSTAND_REQUIREMENT (GPT-OSS) interprets later in the pipeline.
    requirement_text: str


class DocumentRequestCreate(BaseModel):
    client_id: uuid.UUID
    service_id: uuid.UUID | None = None
    sub_service_id: uuid.UUID | None = None
    description: str | None = None
    requested_documents: list[RequestedDocumentCreate]

    # Attachments are always optional and are NOT accepted here: this is a
    # plain JSON body and attachments are real files, which need multipart
    # form data. A request can be created with zero attachments and they
    # can be added any time afterward (before or after the client starts
    # uploading) via POST /requests/{request_id}/attachments — see
    # app/api/v1/request_attachments.py. DocumentRequestRead below reflects
    # whatever attachments exist at read time.


class RequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    raw_text: str
    status: RequirementStatus
    normalized_spec: dict | None


class RequestedDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: str
    is_mandatory: bool
    display_order: int
    requirement: RequirementRead | None


class DocumentRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    service_id: uuid.UUID | None
    sub_service_id: uuid.UUID | None
    created_by_user_id: uuid.UUID
    status: RequestStatus
    description: str | None
    requested_documents: list[RequestedDocumentRead]
    # attachments: list[RequestAttachmentRead]
    created_at: datetime
