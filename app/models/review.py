import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ReviewDecision

if TYPE_CHECKING:
    from app.models.upload import DocumentUpload


class ReviewAction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A CA/Sub-CA's manual decision on an upload — primarily for
    NEEDS_REVIEW items, but also usable to override an AI VALID/INVALID
    call. The CA remains the final authority (plan doc section 8)."""

    __tablename__ = "review_actions"

    document_upload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_uploads.id"), nullable=False, index=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decision: Mapped[ReviewDecision] = mapped_column(
        Enum(ReviewDecision, name="review_decision", native_enum=True), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    document_upload: Mapped["DocumentUpload"] = relationship(back_populates="review_actions")


class AuditEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Generic lifecycle-history log. entity_type + entity_id point at
    any other table's row (document_request, document_upload, etc.) —
    kept generic rather than one FK per entity type so new entities don't
    require a schema change to get audit coverage."""

    __tablename__ = "audit_events"

    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    event_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)