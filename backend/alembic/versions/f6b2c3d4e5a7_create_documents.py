"""create documents

Revision ID: f6b2c3d4e5a7
Revises: e5a1b2c3d4f6
Hand-authored migration; PostgreSQL execution is pending user verification.

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6b2c3d4e5a7"
down_revision: Union[str, Sequence[str], None] = "e5a1b2c3d4f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("declared_content_type", sa.String(length=127), nullable=False),
        sa.Column("detected_content_type", sa.String(length=127), nullable=True),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("stored_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("gcs_object_key", sa.String(length=1024), nullable=False),
        sa.Column("gcs_generation", sa.BigInteger(), nullable=True),
        sa.Column("gcs_crc32c", sa.String(length=32), nullable=True),
        sa.Column(
            "upload_status",
            sa.String(length=32),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "processing_status",
            sa.String(length=32),
            server_default="NOT_QUEUED",
            nullable=False,
        ),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(original_filename) BETWEEN 1 AND 255",
            name="ck_documents_original_filename_length",
        ),
        sa.CheckConstraint(
            "length(declared_content_type) BETWEEN 1 AND 127",
            name="ck_documents_declared_content_type_length",
        ),
        sa.CheckConstraint(
            "declared_size_bytes > 0",
            name="ck_documents_declared_size_positive",
        ),
        sa.CheckConstraint(
            "stored_size_bytes IS NULL OR stored_size_bytes > 0",
            name="ck_documents_stored_size_positive",
        ),
        sa.CheckConstraint(
            "length(gcs_object_key) > 0",
            name="ck_documents_gcs_object_key_nonempty",
        ),
        sa.CheckConstraint(
            "upload_status IN ('PENDING', 'STORED', 'EXPIRED', 'DELETED')",
            name="ck_documents_upload_status",
        ),
        sa.CheckConstraint(
            "processing_status IN "
            "('NOT_QUEUED', 'QUEUED', 'PROCESSING', 'READY', "
            "'REJECTED', 'FAILED')",
            name="ck_documents_processing_status",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gcs_object_key"),
    )
    op.create_index(
        op.f("ix_documents_knowledge_base_id"),
        "documents",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_documents_uploaded_by_user_id"),
        "documents",
        ["uploaded_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_documents_upload_status_expires_at",
        "documents",
        ["upload_status", "upload_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_documents_upload_status_expires_at", table_name="documents")
    op.drop_index(op.f("ix_documents_uploaded_by_user_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_knowledge_base_id"), table_name="documents")
    op.drop_table("documents")
