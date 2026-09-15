import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Service(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Top-level business service (e.g. 'Tax Filing', 'GST Compliance').
    Lookup table — CAs pick these when creating a document_request."""

    __tablename__ = "services"

    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    sub_services: Mapped[list["SubService"]] = relationship(back_populates="service")


class SubService(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sub_services"

    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    service: Mapped["Service"] = relationship(back_populates="sub_services")