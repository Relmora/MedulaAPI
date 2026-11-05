"""add relations artifact location

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-11-05

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, Sequence[str], None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "relations_storage_object_key",
            sa.String(length=1024),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "relations_storage_version",
            sa.String(length=255),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "relations_storage_version")
    op.drop_column("documents", "relations_storage_object_key")
