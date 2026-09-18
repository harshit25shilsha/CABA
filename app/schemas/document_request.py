import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import RequestStatus, RequirementStatus


class RequestedDocumentCreate(BaseModel):
    document_type: str
    is_mandatory: bool = True
    display_order: int = 0
    # The CA's freeform natural-language requirement — this is what
    # UNDERSTAND_REQUIREMENT (GPT-OSS) interprets later in the pipeline.
    requirement_text: str


class DocumentRequestCreate(BaseModel):
    client_id: uuid.UUID
    # TODO: replace with the authenticated CA's id once auth is built —
    # no auth dependency exists yet, so the caller states who they are.
    created_by_user_id: uuid.UUID
    description: str | None = None
    requested_documents: list[RequestedDocumentCreate]


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
    status: RequestStatus
    description: str | None
    requested_documents: list[RequestedDocumentRead]
    created_at: datetime
