import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import RequestStatus, RequirementStatus

if TYPE_CHECKING:
    from app.models.client import Client
    from app.models.upload import DocumentUpload
    from app.models.user import User


class DocumentRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A CA-created request for a client: 'give me these documents,
    meeting these requirements'. One request can list several
    requested_documents, each with its own requirement text."""

    __tablename__ = "document_requests"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=True
    )
    sub_service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sub_services.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, name="request_status", native_enum=True),
        nullable=False,
        default=RequestStatus.DRAFT,
    )

    client: Mapped["Client"] = relationship(back_populates="document_requests")
    created_by: Mapped["User"] = relationship(back_populates="document_requests")
    requested_documents: Mapped[list["RequestedDocument"]] = relationship(
        back_populates="document_request", cascade="all, delete-orphan"
    )



class RequestedDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One expected document within a request (e.g. 'Bank Statement').
    Holds the CA's requirement text via its Requirement child row."""

    __tablename__ = "requested_documents"

    document_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_requests.id"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document_request: Mapped["DocumentRequest"] = relationship(
        back_populates="requested_documents"
    )
    requirement: Mapped["Requirement | None"] = relationship(
        back_populates="requested_document", uselist=False, cascade="all, delete-orphan"
    )
    uploads: Mapped[list["DocumentUpload"]] = relationship(back_populates="requested_document")


class Requirement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The CA's natural-language requirement text plus the LLM's
    normalized structured interpretation of it (see plan doc section 6:
    Semantic Requirement Understanding)."""

    __tablename__ = "requirements"

    requested_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requested_documents.id"), nullable=False, unique=True
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[RequirementStatus] = mapped_column(
        Enum(RequirementStatus, name="requirement_status", native_enum=True),
        nullable=False,
        default=RequirementStatus.PENDING_INTERPRETATION,
    )

    requested_document: Mapped["RequestedDocument"] = relationship(back_populates="requirement")