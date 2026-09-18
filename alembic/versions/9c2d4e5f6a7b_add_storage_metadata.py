"""add storage resource metadata

Revision ID: 9c2d4e5f6a7b
Revises: 8a3f2c1d9e4b
"""
from alembic import op
import sqlalchemy as sa

revision = "9c2d4e5f6a7b"
down_revision = "8a3f2c1d9e4b"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("document_uploads", sa.Column("storage_resource_type", sa.String(length=20), nullable=True))
    op.add_column("document_uploads", sa.Column("storage_format", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("storage_resource_type", sa.String(length=20), nullable=True))
    op.add_column("documents", sa.Column("storage_format", sa.String(length=50), nullable=True))
    op.add_column("request_attachments", sa.Column("storage_resource_type", sa.String(length=20), nullable=True))
    op.add_column("request_attachments", sa.Column("storage_format", sa.String(length=50), nullable=True))
    # Existing rows need values before constraints can become NOT NULL.
    # Phase 1 currently stores only supported PDF/DOCX/JPEG/PNG uploads.
    op.execute("UPDATE document_uploads SET storage_resource_type = CASE WHEN lower(original_filename) LIKE '%%.jpg' OR lower(original_filename) LIKE '%%.jpeg' OR lower(original_filename) LIKE '%%.png' THEN 'image' ELSE 'raw' END")
    op.execute("UPDATE document_uploads SET storage_format = lower(split_part(original_filename, '.', array_length(string_to_array(original_filename, '.'), 1)))")
    op.execute("UPDATE documents SET storage_resource_type = du.storage_resource_type, storage_format = du.storage_format FROM document_uploads du WHERE documents.document_upload_id = du.id")
    op.execute("UPDATE request_attachments SET storage_resource_type = CASE WHEN lower(original_filename) LIKE '%%.jpg' OR lower(original_filename) LIKE '%%.jpeg' OR lower(original_filename) LIKE '%%.png' THEN 'image' ELSE 'raw' END")
    op.execute("UPDATE request_attachments SET storage_format = lower(split_part(original_filename, '.', array_length(string_to_array(original_filename, '.'), 1)))")
    op.alter_column("document_uploads", "storage_resource_type", nullable=False)
    op.alter_column("document_uploads", "storage_format", nullable=False)
    op.alter_column("documents", "storage_resource_type", nullable=False)
    op.alter_column("documents", "storage_format", nullable=False)
    op.alter_column("request_attachments", "storage_resource_type", nullable=False)
    op.alter_column("request_attachments", "storage_format", nullable=False)

def downgrade() -> None:
    op.drop_column("request_attachments", "storage_format")
    op.drop_column("request_attachments", "storage_resource_type")
    op.drop_column("documents", "storage_format")
    op.drop_column("documents", "storage_resource_type")
    op.drop_column("document_uploads", "storage_format")
    op.drop_column("document_uploads", "storage_resource_type")
