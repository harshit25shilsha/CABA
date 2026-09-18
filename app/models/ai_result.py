import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ProcessingStage, ValidationCheckStatus

if TYPE_CHECKING:
    from app.models.upload import DocumentUpload


class AIProcessingResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One AI pipeline stage's output for one upload (classification,
    extraction, or requirement understanding). raw_output stores the
    structured result; confidence drives NEEDS_REVIEW routing."""

    __tablename__ = "ai_processing_results"

    document_upload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_uploads.id"), nullable=False, index=True
    )
    stage: Mapped[ProcessingStage] = mapped_column(
        Enum(ProcessingStage, name="processing_stage", native_enum=True), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    document_upload: Mapped["DocumentUpload"] = relationship(
        back_populates="ai_processing_results"
    )


class ValidationResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One deterministic-or-AI-assisted check against a requirement
    (e.g. 'financial_year_matches', 'account_number_present'). evidence
    holds the supporting detail shown to the CA/client for the decision."""

    __tablename__ = "validation_results"

    document_upload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_uploads.id"), nullable=False, index=True
    )
    check_name: Mapped[str] = mapped_column(String(150), nullable=False)
    expected_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    actual_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ValidationCheckStatus] = mapped_column(
        Enum(ValidationCheckStatus, name="validation_check_status", native_enum=True),
        nullable=False,
    )

    document_upload: Mapped["DocumentUpload"] = relationship(back_populates="validation_results")