"""add normalized artifact location

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-31

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "normalized_storage_object_key",
            sa.String(length=1024),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("normalized_storage_version", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "normalized_storage_version")
    op.drop_column("documents", "normalized_storage_object_key")
