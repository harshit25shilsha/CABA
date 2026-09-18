import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClientCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    pan_number: str | None = None
    profile_data: dict = {}
    # TODO: replace with the authenticated CA's id once auth is built —
    # no auth dependency exists yet, so the caller states who they are.
    created_by_user_id: uuid.UUID


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    pan_number: str | None
    created_at: datetime
