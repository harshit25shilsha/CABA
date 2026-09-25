"""Persistent state for a document validation requested by Java.

Java remains the source of truth for clients, CA requirements, and uploaded
documents.  This table stores only the inputs and delivery state AI Brain
needs to process a request asynchronously and reliably send its verdict.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ExternalValidationStatus, ValidationVerdict


class ExternalValidationJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "external_validation_jobs"

    # The opaque ID returned immediately to Java.  It is deliberately separate
    # from the internal UUID so external IDs can carry the stable `aib_` prefix.
    upload_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    external_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # Immutable Java-supplied processing inputs.
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(150), nullable=False)
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    client_profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Processing state.  The lease prevents two redelivered Celery messages
    # from processing the same job concurrently.
    status: Mapped[ExternalValidationStatus] = mapped_column(
        Enum(
            ExternalValidationStatus,
            name="external_validation_status",
            native_enum=True,
        ),
        nullable=False,
        default=ExternalValidationStatus.QUEUED,
        index=True,
    )
    processing_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Persisted terminal result.  Webhook retries are built only from these
    # fields; they never re-run the AI pipeline.
    verdict: Mapped[ValidationVerdict | None] = mapped_column(
        Enum(ValidationVerdict, name="validation_verdict", native_enum=True), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

    # Durable callback-delivery state.
    callback_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    callback_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    callback_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_callback_error: Mapped[str | None] = mapped_column(Text, nullable=True)
