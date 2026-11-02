"""add embedded artifact location

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-11-02

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "embedded_storage_object_key",
            sa.String(length=1024),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("embedded_storage_version", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "embedded_storage_version")
    op.drop_column("documents", "embedded_storage_object_key")
