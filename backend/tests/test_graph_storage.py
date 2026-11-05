from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.ingestion.graph_storage import (
    GraphStorageError,
    PostgresGraphStore,
    normalize_entity_name,
)
from backend.ingestion.relation_extraction import (
    ChunkRelations,
    ExtractedEntity,
    ExtractedRelation,
    RelationExtractedDocument,
    RelationExtractionConfiguration,
    RelationExtractionStatistics,
)
from backend.ingestion.stages import GraphStoreStage, RelationsArtifact
from backend.models import (
    Base,
    Document,
    Entity,
    EntityRelationship,
    KnowledgeBase,
    User,
    Workspace,
)
from backend.object_storage.fake import FakeObjectStorage


@pytest.fixture
def graph_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def add_document(factory, label: str) -> Document:
    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    with factory() as db, db.begin():
        user = User(username=f"owner-{label}", password_hash="hash", is_active=True)
        db.add(user)
        db.flush()
        workspace = Workspace(name=f"Workspace {label}", owner_user_id=user.id)
        db.add(workspace)
        db.flush()
        knowledge_base = KnowledgeBase(
            name=f"Knowledge {label}", workspace_id=workspace.id
        )
        db.add(knowledge_base)
        db.flush()
        document = Document(
            knowledge_base_id=knowledge_base.id,
            uploaded_by_user_id=user.id,
            original_filename=f"{label}.txt",
            declared_content_type="text/plain",
            declared_size_bytes=10,
            stored_size_bytes=10,
            storage_provider="gcs",
            storage_bucket="documents",
            storage_object_key=f"documents/{uuid4()}/original",
            storage_version="1",
            upload_status="STORED",
            processing_status="PROCESSING",
            upload_expires_at=now + timedelta(minutes=10),
            uploaded_at=now,
        )
        db.add(document)
        db.flush()
        document_id = document.id
    with factory() as db:
        return db.get(Document, document_id)


def relation_document(document_id: UUID) -> RelationExtractedDocument:
    chunks = []
    names = (("OpenAI", "ChatGPT"), ("Open AI Company", "ChatGPT!"))
    for index, (organization_name, product_name) in enumerate(names):
        organization_id = uuid4()
        product_id = uuid4()
        chunks.append(
            ChunkRelations(
                chunk_index=index,
                chunk_id=uuid4(),
                source_content_hash=str(index) * 64,
                entities=(
                    ExtractedEntity(
                        entity_id=organization_id,
                        name=organization_name,
                        type="ORGANIZATION",
                    ),
                    ExtractedEntity(
                        entity_id=product_id,
                        name=product_name,
                        type="PRODUCT",
                    ),
                ),
                relations=(
                    ExtractedRelation(
                        relation_id=uuid4(),
                        source_entity_id=organization_id,
                        target_entity_id=product_id,
                        type="CREATED",
                        evidence=f"{organization_name} created {product_name}",
                        confidence=0.95,
                    ),
                ),
            )
        )
    return RelationExtractedDocument(
        document_id=document_id,
        source_chunked_object_key=f"documents/{document_id}/chunks.json",
        source_chunked_storage_version="1",
        chunked_schema_version=1,
        configuration=RelationExtractionConfiguration(
            provider="fake",
            model="fake-v1",
        ),
        configuration_hash="a" * 64,
        chunks=tuple(chunks),
        statistics=RelationExtractionStatistics(
            chunk_count=2,
            entity_count=4,
            relation_count=2,
            dropped_entity_count=0,
            dropped_relation_count=0,
        ),
    )


def test_entity_normalization_handles_case_spacing_punctuation_and_org_suffixes():
    assert normalize_entity_name(" OpenAI, Inc. ", "ORGANIZATION") == "openai"
    assert normalize_entity_name("Open AI Company", "ORGANIZATION") == "openai"
    assert normalize_entity_name("ChatGPT!", "PRODUCT") == "chatgpt"


def test_graph_store_resolves_across_chunks_and_is_idempotent(graph_database):
    document = add_document(graph_database, "one")
    extracted = relation_document(document.id)
    store = PostgresGraphStore(graph_database)

    first = store.write(extracted)
    second = store.write(extracted)

    assert first.entity_count == 2
    assert first.relationship_count == 1
    assert first.created_entity_count == 2
    assert first.created_relationship_count == 1
    assert second.created_entity_count == 0
    assert second.created_relationship_count == 0
    with graph_database() as db:
        assert db.scalar(select(func.count()).select_from(Entity)) == 2
        assert db.scalar(select(func.count()).select_from(EntityRelationship)) == 1
        relationship = db.scalar(select(EntityRelationship))
        assert relationship.document_id == document.id
        assert relationship.chunk_id == extracted.chunks[0].chunk_id


def test_graph_store_never_merges_entities_across_knowledge_bases(graph_database):
    first_document = add_document(graph_database, "first")
    second_document = add_document(graph_database, "second")
    store = PostgresGraphStore(graph_database)

    store.write(relation_document(first_document.id))
    store.write(relation_document(second_document.id))

    with graph_database() as db:
        assert db.scalar(select(func.count()).select_from(Entity)) == 4
        assert db.scalar(select(func.count()).select_from(EntityRelationship)) == 2


def test_graph_stage_reads_and_validates_persisted_relation_artifact(graph_database):
    document = add_document(graph_database, "stage")
    extracted = relation_document(document.id)
    storage = FakeObjectStorage()
    object_key = f"documents/{document.id}/relations.json"
    metadata = storage.write_object(
        object_key,
        extracted.model_dump_json().encode(),
        content_type="application/json",
    )
    artifact = RelationsArtifact(extracted, object_key, metadata.version)
    stage = GraphStoreStage(PostgresGraphStore(graph_database), storage)

    result = stage.execute(artifact)

    assert result.document_id == document.id
    assert result.created_entity_count == 2
    storage.object_contents[object_key] = b"not-json"
    with pytest.raises(GraphStorageError) as raised:
        stage.execute(artifact)
    assert raised.value.code == "GRAPH_INPUT_INVALID"
