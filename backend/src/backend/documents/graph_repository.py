"""Read document and knowledge-base graph nodes and edges from PostgreSQL."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from backend.models import Entity, EntityRelationship


@dataclass(frozen=True)
class GraphNode:
    id: UUID
    name: str
    entity_type: str


@dataclass(frozen=True)
class GraphEdge:
    id: UUID
    source: UUID
    target: UUID
    predicate: str
    chunk_id: UUID


@dataclass(frozen=True)
class DocumentGraph:
    document_id: UUID
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


@dataclass(frozen=True)
class KnowledgeBaseGraph:
    knowledge_base_id: UUID
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


def read_knowledge_base_graph(
    db: Session,
    *,
    knowledge_base_id: UUID,
) -> KnowledgeBaseGraph:
    """Return every canonical entity and relationship in a knowledge base."""

    entities = db.scalars(
        select(Entity)
        .where(Entity.knowledge_base_id == knowledge_base_id)
        .order_by(Entity.created_at, Entity.id)
    ).all()
    relationships = db.scalars(
        select(EntityRelationship)
        .where(EntityRelationship.knowledge_base_id == knowledge_base_id)
        .order_by(EntityRelationship.created_at, EntityRelationship.id)
    ).all()
    return KnowledgeBaseGraph(
        knowledge_base_id=knowledge_base_id,
        nodes=tuple(
            GraphNode(
                id=entity.id,
                name=entity.name,
                entity_type=entity.entity_type,
            )
            for entity in entities
        ),
        edges=tuple(
            GraphEdge(
                id=relationship.id,
                source=relationship.subject_entity_id,
                target=relationship.object_entity_id,
                predicate=relationship.predicate,
                chunk_id=relationship.chunk_id,
            )
            for relationship in relationships
        ),
    )


def read_document_graph(
    db: Session,
    *,
    knowledge_base_id: UUID,
    document_id: UUID,
) -> DocumentGraph:
    """Return the nodes participating in edges first sourced from a document."""

    subject = aliased(Entity)
    object_entity = aliased(Entity)
    statement = (
        select(EntityRelationship, subject, object_entity)
        .join(subject, subject.id == EntityRelationship.subject_entity_id)
        .join(object_entity, object_entity.id == EntityRelationship.object_entity_id)
        .where(
            EntityRelationship.knowledge_base_id == knowledge_base_id,
            EntityRelationship.document_id == document_id,
        )
        .order_by(EntityRelationship.created_at, EntityRelationship.id)
    )

    nodes: dict[UUID, GraphNode] = {}
    edges: list[GraphEdge] = []
    for relationship, subject_entity, target_entity in db.execute(statement):
        nodes.setdefault(
            subject_entity.id,
            GraphNode(
                id=subject_entity.id,
                name=subject_entity.name,
                entity_type=subject_entity.entity_type,
            ),
        )
        nodes.setdefault(
            target_entity.id,
            GraphNode(
                id=target_entity.id,
                name=target_entity.name,
                entity_type=target_entity.entity_type,
            ),
        )
        edges.append(
            GraphEdge(
                id=relationship.id,
                source=relationship.subject_entity_id,
                target=relationship.object_entity_id,
                predicate=relationship.predicate,
                chunk_id=relationship.chunk_id,
            )
        )

    return DocumentGraph(
        document_id=document_id,
        nodes=tuple(nodes.values()),
        edges=tuple(edges),
    )
