"""create graph entities and relationships

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-11-05

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint("length(name) > 0", name="ck_entities_name_nonempty"),
        sa.CheckConstraint(
            "length(normalized_name) > 0",
            name="ck_entities_normalized_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(entity_type) > 0",
            name="ck_entities_type_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "entity_type",
            "normalized_name",
            name="uq_entities_identity",
        ),
        sa.UniqueConstraint(
            "id",
            "knowledge_base_id",
            name="uq_entities_id_knowledge_base",
        ),
    )
    op.create_index(
        "ix_entities_knowledge_base_id",
        "entities",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_table(
        "entity_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("subject_entity_id", sa.Uuid(), nullable=False),
        sa.Column("predicate", sa.String(length=64), nullable=False),
        sa.Column("object_entity_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(predicate) > 0",
            name="ck_entity_relationships_predicate_nonempty",
        ),
        sa.CheckConstraint(
            "subject_entity_id <> object_entity_id",
            name="ck_entity_relationships_distinct_endpoints",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subject_entity_id", "knowledge_base_id"],
            ["entities.id", "entities.knowledge_base_id"],
            ondelete="CASCADE",
            name="fk_entity_relationships_subject_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["object_entity_id", "knowledge_base_id"],
            ["entities.id", "entities.knowledge_base_id"],
            ondelete="CASCADE",
            name="fk_entity_relationships_object_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "subject_entity_id",
            "predicate",
            "object_entity_id",
            name="uq_entity_relationships_edge",
        ),
    )
    op.create_index(
        "ix_entity_relationships_knowledge_base",
        "entity_relationships",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_relationships_subject",
        "entity_relationships",
        ["subject_entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_relationships_object",
        "entity_relationships",
        ["object_entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_relationships_document_chunk",
        "entity_relationships",
        ["document_id", "chunk_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_entity_relationships_document_chunk",
        table_name="entity_relationships",
    )
    op.drop_index(
        "ix_entity_relationships_object",
        table_name="entity_relationships",
    )
    op.drop_index(
        "ix_entity_relationships_subject",
        table_name="entity_relationships",
    )
    op.drop_index(
        "ix_entity_relationships_knowledge_base",
        table_name="entity_relationships",
    )
    op.drop_table("entity_relationships")
    op.drop_index("ix_entities_knowledge_base_id", table_name="entities")
    op.drop_table("entities")
