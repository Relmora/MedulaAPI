"""create ingestion job attempts

Revision ID: b8d4e6f7a9c1
Revises: 5d3dc3ad1dfa
Create Date: 2026-10-31

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d4e6f7a9c1"
down_revision: Union[str, Sequence[str], None] = "5d3dc3ad1dfa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create durable history for individual worker executions."""
    op.create_table(
        "ingestion_job_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="RUNNING",
            nullable=False,
        ),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_class", sa.String(length=32), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_ingestion_job_attempts_number_positive",
        ),
        sa.CheckConstraint(
            "current_stage IS NULL OR length(current_stage) BETWEEN 1 AND 64",
            name="ck_ingestion_job_attempts_stage_length",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'ABANDONED', "
            "'CANCELLED')",
            name="ck_ingestion_job_attempts_status",
        ),
        sa.CheckConstraint(
            "length(worker_id) BETWEEN 1 AND 255",
            name="ck_ingestion_job_attempts_worker_id_length",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["ingestion_jobs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "attempt_number",
            name="uq_ingestion_job_attempts_job_number",
        ),
    )
    op.create_index(
        op.f("ix_ingestion_job_attempts_job_id"),
        "ingestion_job_attempts",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_job_attempts_job_status",
        "ingestion_job_attempts",
        ["job_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_job_attempts_expired_lease",
        "ingestion_job_attempts",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "uq_ingestion_job_attempts_one_running",
        "ingestion_job_attempts",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
    )


def downgrade() -> None:
    """Remove worker-attempt history."""
    op.drop_index(
        "uq_ingestion_job_attempts_one_running",
        table_name="ingestion_job_attempts",
        postgresql_where=sa.text("status = 'RUNNING'"),
    )
    op.drop_index(
        "ix_ingestion_job_attempts_expired_lease",
        table_name="ingestion_job_attempts",
    )
    op.drop_index(
        "ix_ingestion_job_attempts_job_status",
        table_name="ingestion_job_attempts",
    )
    op.drop_index(
        op.f("ix_ingestion_job_attempts_job_id"),
        table_name="ingestion_job_attempts",
    )
    op.drop_table("ingestion_job_attempts")
