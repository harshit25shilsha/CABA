"""add request_attachments

Revision ID: 8a3f2c1d9e4b
Revises: 0f88871b47c6
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8a3f2c1d9e4b'
down_revision: Union[str, Sequence[str], None] = '0f88871b47c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'request_attachments',
        sa.Column('document_request_id', sa.UUID(), nullable=False),
        sa.Column('uploaded_by_user_id', sa.UUID(), nullable=False),
        sa.Column(
            'attachment_type',
            sa.Enum('GUIDANCE', 'TEMPLATE', 'REFERENCE', 'OTHER', name='attachment_type'),
            nullable=False,
        ),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('storage_provider', sa.String(length=50), nullable=False),
        sa.Column('storage_public_id', sa.String(length=500), nullable=False),
        sa.Column('storage_url', sa.String(length=1000), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=150), nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['document_request_id'],
            ['document_requests.id'],
            name=op.f('fk_request_attachments_document_request_id_document_requests'),
        ),
        sa.ForeignKeyConstraint(
            ['uploaded_by_user_id'],
            ['users.id'],
            name=op.f('fk_request_attachments_uploaded_by_user_id_users'),
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_request_attachments')),
    )
    op.create_index(
        op.f('ix_request_attachments_document_request_id'),
        'request_attachments',
        ['document_request_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_request_attachments_document_request_id'), table_name='request_attachments'
    )
    op.drop_table('request_attachments')
    sa.Enum(name='attachment_type').drop(op.get_bind(), checkfirst=True)
