"""make document storage provider neutral

Revision ID: a7c3d4e5f6b8
Revises: f6b2c3d4e5a7
Hand-authored migration; PostgreSQL execution is pending user verification.

The upload-intent API did not exist at this revision, so the documents table is
expected to be empty when the new required provider and bucket columns are added.

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3d4e5f6b8"
down_revision: Union[str, Sequence[str], None] = "f6b2c3d4e5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace GCS-specific storage columns with provider-neutral metadata."""
    op.drop_constraint("documents_gcs_object_key_key", "documents", type_="unique")
    op.drop_constraint(
        "ck_documents_gcs_object_key_nonempty", "documents", type_="check"
    )
    op.alter_column("documents", "gcs_object_key", new_column_name="storage_object_key")
    op.alter_column(
        "documents",
        "gcs_generation",
        existing_type=sa.BigInteger(),
        type_=sa.String(length=255),
        new_column_name="storage_version",
        postgresql_using="gcs_generation::text",
    )
    op.alter_column(
        "documents",
        "gcs_crc32c",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        new_column_name="storage_checksum",
    )
    op.add_column(
        "documents", sa.Column("storage_provider", sa.String(length=32), nullable=False)
    )
    op.add_column(
        "documents", sa.Column("storage_bucket", sa.String(length=255), nullable=False)
    )
    op.add_column(
        "documents",
        sa.Column("storage_checksum_algorithm", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_documents_storage_provider_nonempty",
        "documents",
        "length(storage_provider) > 0",
    )
    op.create_check_constraint(
        "ck_documents_storage_bucket_nonempty",
        "documents",
        "length(storage_bucket) > 0",
    )
    op.create_check_constraint(
        "ck_documents_storage_object_key_nonempty",
        "documents",
        "length(storage_object_key) > 0",
    )
    op.create_unique_constraint(
        "uq_documents_storage_location",
        "documents",
        ["storage_provider", "storage_bucket", "storage_object_key"],
    )


def downgrade() -> None:
    """Restore the original GCS-specific document storage columns."""
    op.drop_constraint("uq_documents_storage_location", "documents", type_="unique")
    op.drop_constraint(
        "ck_documents_storage_object_key_nonempty", "documents", type_="check"
    )
    op.drop_constraint(
        "ck_documents_storage_bucket_nonempty", "documents", type_="check"
    )
    op.drop_constraint(
        "ck_documents_storage_provider_nonempty", "documents", type_="check"
    )
    op.drop_column("documents", "storage_checksum_algorithm")
    op.drop_column("documents", "storage_bucket")
    op.drop_column("documents", "storage_provider")
    op.alter_column(
        "documents",
        "storage_checksum",
        existing_type=sa.String(length=128),
        type_=sa.String(length=32),
        new_column_name="gcs_crc32c",
    )
    op.alter_column(
        "documents",
        "storage_version",
        existing_type=sa.String(length=255),
        type_=sa.BigInteger(),
        new_column_name="gcs_generation",
        postgresql_using="storage_version::bigint",
    )
    op.alter_column("documents", "storage_object_key", new_column_name="gcs_object_key")
    op.create_check_constraint(
        "ck_documents_gcs_object_key_nonempty",
        "documents",
        "length(gcs_object_key) > 0",
    )
    op.create_unique_constraint(
        "documents_gcs_object_key_key", "documents", ["gcs_object_key"]
    )
