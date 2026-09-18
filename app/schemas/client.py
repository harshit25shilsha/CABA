import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClientCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    pan_number: str | None = None
    profile_data: dict = {}


class ClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    pan_number: str | None
    created_at: datetime
