import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document_request import DocumentRequest
    from app.models.user import User


class Client(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A CA's client. profile_data holds structured fields (PAN, entity
    name, etc.) used for deterministic client-profile matching during
    validation — kept as JSONB since the field set varies by client type."""

    __tablename__ = "clients"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pan_number: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    profile_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    created_by: Mapped["User"] = relationship(back_populates="clients")
    document_requests: Mapped[list["DocumentRequest"]] = relationship(back_populates="client")