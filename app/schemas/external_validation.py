"""HTTP contract for Java-originated validation requests."""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class ExternalValidationCreate(BaseModel):
    external_ref: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*:[A-Za-z0-9_.-]+$",
    )
    file_url: str = Field(min_length=1, max_length=2048)
    mime_type: str = Field(min_length=1, max_length=150)
    requirement_text: str = Field(min_length=1)
    client_profile: dict = Field(default_factory=dict)

    @field_validator("external_ref", "requirement_text")
    @classmethod
    def field_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field must not be blank")
        return value

    @field_validator("file_url")
    @classmethod
    def signed_url_must_be_https(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("file_url must be an absolute HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("file_url must not contain user credentials")
        return value

    @field_validator("mime_type")
    @classmethod
    def mime_type_must_be_allowed(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in settings.ALLOWED_MIME_TYPES:
            raise ValueError(f"Unsupported MIME type: {value}")
        return value


class ExternalValidationAccepted(BaseModel):
    upload_id: str
    status: str = "QUEUED"
