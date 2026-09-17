import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UploadStatus

if TYPE_CHECKING:
    from app.models.ai_result import AIProcessingResult, ValidationResult
    from app.models.document_request import RequestedDocument
    from app.models.review import ReviewAction


class DocumentUpload(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Every upload/processing attempt — kept even for INVALID/expired
    attempts (audit trail per plan doc section 10). storage_provider is
    always 'cloudinary' in Phase 1; the field exists so a future provider
    swap doesn't require a schema change."""

    __tablename__ = "document_uploads"

    requested_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requested_documents.id"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )

    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="cloudinary")
    storage_public_id: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_url: Mapped[str] = mapped_column(String(1000), nullable=False)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    upload_attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, name="upload_status", native_enum=True),
        nullable=False,
        default=UploadStatus.UPLOADED,
    )

    requested_document: Mapped["RequestedDocument"] = relationship(back_populates="uploads")
    document: Mapped["Document | None"] = relationship(
        back_populates="document_upload", uselist=False
    )
    ai_processing_results: Mapped[list["AIProcessingResult"]] = relationship(
        back_populates="document_upload", cascade="all, delete-orphan"
    )
    validation_results: Mapped[list["ValidationResult"]] = relationship(
        back_populates="document_upload", cascade="all, delete-orphan"
    )
    review_actions: Mapped[list["ReviewAction"]] = relationship(
        back_populates="document_upload", cascade="all, delete-orphan"
    )


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The accepted/permanent record created once a DocumentUpload is
    validated VALID and moved to permanent Cloudinary storage."""

    __tablename__ = "documents"

    document_upload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_uploads.id"), nullable=False, unique=True
    )
    requested_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requested_documents.id"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    storage_public_id: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    document_upload: Mapped["DocumentUpload"] = relationship(back_populates="document")