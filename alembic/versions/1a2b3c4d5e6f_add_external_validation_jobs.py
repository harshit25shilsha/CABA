"""initial Java external validation schema

Revision ID: 1a2b3c4d5e6f
Revises:
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_validation_jobs",
        sa.Column("upload_id", sa.String(length=64), nullable=False),
        sa.Column("external_ref", sa.String(length=128), nullable=False),
        sa.Column("file_url", sa.String(length=2048), nullable=False),
        sa.Column("mime_type", sa.String(length=150), nullable=False),
        sa.Column("requirement_text", sa.Text(), nullable=False),
        sa.Column("client_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "PROCESSING",
                "COMPLETED",
                "DELIVERY_PENDING",
                "DELIVERY_FAILED",
                name="external_validation_status",
            ),
            nullable=False,
        ),
        sa.Column("processing_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column(
            "verdict",
            sa.Enum("VALID", "INVALID", "NEEDS_REVIEW", name="validation_verdict"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("callback_attempts", sa.Integer(), nullable=False),
        sa.Column("callback_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("callback_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_callback_error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_validation_jobs")),
    )
    op.create_index(
        op.f("ix_external_validation_jobs_upload_id"),
        "external_validation_jobs",
        ["upload_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_external_validation_jobs_external_ref"),
        "external_validation_jobs",
        ["external_ref"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_validation_jobs_status"),
        "external_validation_jobs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_external_validation_jobs_status"), table_name="external_validation_jobs")
    op.drop_index(op.f("ix_external_validation_jobs_external_ref"), table_name="external_validation_jobs")
    op.drop_index(op.f("ix_external_validation_jobs_upload_id"), table_name="external_validation_jobs")
    op.drop_table("external_validation_jobs")
    sa.Enum(name="validation_verdict").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="external_validation_status").drop(op.get_bind(), checkfirst=True)
