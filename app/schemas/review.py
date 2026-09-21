import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ReviewDecision


class ReviewActionCreate(BaseModel):
    decision: ReviewDecision
    notes: str | None = None


class ReviewActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_upload_id: uuid.UUID
    reviewed_by_user_id: uuid.UUID
    decision: ReviewDecision
    notes: str | None
    created_at: datetime
