import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AttachmentType

if TYPE_CHECKING:
    from app.models.document_request import DocumentRequest


class RequestAttachment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A CA-side reference/guidance/template file attached to a
    DocumentRequest — e.g. a sample computation sheet, a filled-example
    form, or written instructions handed to the client alongside the
    request. Deliberately NOT a DocumentUpload: these are never produced
    by the client, never run through the AI Brain / validation pipeline,
    and carry no upload_attempt_number, status, or requirement linkage.
    They exist purely so a CA can hand context to a client; DocumentUpload
    stays the single source of truth for anything the AI pipeline touches.

    Storage fields mirror DocumentUpload's shape for consistency (same
    provider, same public_id/url pattern) but this is an independent
    table — nothing here is read by the AI Brain, Celery tasks, or the
    document_pipeline.
    """

    __tablename__ = "request_attachments"

    document_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_requests.id"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    attachment_type: Mapped[AttachmentType] = mapped_column(
        Enum(AttachmentType, name="attachment_type", native_enum=True),
        nullable=False,
        default=AttachmentType.OTHER,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="cloudinary")
    storage_public_id: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_format: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_url: Mapped[str] = mapped_column(String(1000), nullable=False)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    document_request: Mapped["DocumentRequest"] = relationship(back_populates="attachments")
