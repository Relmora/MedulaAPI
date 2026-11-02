"""create chunk embeddings

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-11-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_config_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("source_object_key", sa.String(length=1024), nullable=False),
        sa.Column("source_storage_version", sa.String(length=255), nullable=True),
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
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_chunk_embeddings_chunk_index_nonnegative",
        ),
        sa.CheckConstraint(
            "length(chunk_text) > 0",
            name="ck_chunk_embeddings_text_nonempty",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_chunk_embeddings_content_hash_length",
        ),
        sa.CheckConstraint(
            "embedding_dimensions = 768",
            name="ck_chunk_embeddings_dimensions",
        ),
        sa.CheckConstraint(
            "length(embedding_config_hash) = 64",
            name="ck_chunk_embeddings_config_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_id",
            "embedding_config_hash",
            name="uq_chunk_embeddings_document_chunk_config",
        ),
    )
    op.create_index(
        "ix_chunk_embeddings_workspace_knowledge_base",
        "chunk_embeddings",
        ["workspace_id", "knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        "ix_chunk_embeddings_document_id",
        "chunk_embeddings",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_chunk_embeddings_embedding_hnsw",
        "chunk_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chunk_embeddings_embedding_hnsw",
        table_name="chunk_embeddings",
        postgresql_using="hnsw",
    )
    op.drop_index(
        "ix_chunk_embeddings_document_id",
        table_name="chunk_embeddings",
    )
    op.drop_index(
        "ix_chunk_embeddings_workspace_knowledge_base",
        table_name="chunk_embeddings",
    )
    op.drop_table("chunk_embeddings")
