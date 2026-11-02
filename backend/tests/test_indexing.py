import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.ingestion.chunking import (
    ChunkedDocument,
    ChunkingConfig,
    ChunkingStatistics,
    ChunkSourceSpan,
    DocumentChunk,
)
from backend.ingestion.embedding import (
    ChunkEmbedding,
    EmbeddedDocument,
    EmbeddingConfiguration,
    EmbeddingStatistics,
)
from backend.ingestion.indexing import (
    IndexChunk,
    IndexDocument,
    IndexingError,
    IndexingTransientError,
    IndexWriteResult,
    PgVectorIndex,
)
from backend.ingestion.stages import EmbeddedArtifact, IndexStage
from backend.models import (
    Base,
    Document,
    IndexedChunk,
    KnowledgeBase,
    User,
    Workspace,
)
from backend.object_storage.fake import FakeObjectStorage


@pytest.fixture
def indexing_database():
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


def chunked_document(*texts: str) -> ChunkedDocument:
    chunks = tuple(
        DocumentChunk(
            chunk_index=index,
            chunk_id=uuid4(),
            text=text,
            source_spans=(
                ChunkSourceSpan(
                    source_block_index=index,
                    normalized_start_offset=0,
                    normalized_end_offset=len(text),
                ),
            ),
            character_count=len(text),
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        for index, text in enumerate(texts)
    )
    sizes = [len(text) for text in texts]
    return ChunkedDocument(
        document_id=uuid4(),
        source_normalized_object_key="normalized.json",
        source_normalized_storage_version="3",
        normalized_schema_version=1,
        chunker_name="test",
        chunker_version="1",
        configuration=ChunkingConfig(),
        configuration_hash="0" * 64,
        chunks=chunks,
        statistics=ChunkingStatistics(
            source_block_count=len(chunks),
            chunk_count=len(chunks),
            minimum_chunk_characters=min(sizes),
            maximum_chunk_characters=max(sizes),
            average_chunk_characters=sum(sizes) / len(sizes),
        ),
    )


def stored_artifacts(storage: FakeObjectStorage, *texts: str) -> EmbeddedArtifact:
    chunked = chunked_document(*texts)
    chunked_key = f"documents/{chunked.document_id}/chunked/chunks.json"
    chunked_metadata = storage.write_object(
        chunked_key,
        chunked.model_dump_json().encode(),
        content_type="application/json",
    )
    dimensions = 3
    configuration = EmbeddingConfiguration(
        provider="fake",
        model="fake-v1",
        dimensions=dimensions,
        batch_size=2,
    )
    configuration_hash = hashlib.sha256(
        json.dumps(
            configuration.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    embedded = EmbeddedDocument(
        document_id=chunked.document_id,
        source_chunked_object_key=chunked_key,
        source_chunked_storage_version=chunked_metadata.version,
        chunked_schema_version=chunked.schema_version,
        configuration=configuration,
        configuration_hash=configuration_hash,
        embeddings=tuple(
            ChunkEmbedding(
                chunk_index=chunk.chunk_index,
                chunk_id=chunk.chunk_id,
                source_content_hash=chunk.content_hash,
                vector=(float(chunk.chunk_index), 0.5, 1.0),
                dimensions=dimensions,
            )
            for chunk in chunked.chunks
        ),
        statistics=EmbeddingStatistics(
            chunk_count=len(chunked.chunks),
            dimensions=dimensions,
            batch_count=(len(chunked.chunks) + 1) // 2,
        ),
    )
    embedded_key = f"documents/{chunked.document_id}/embedded/embeddings.json"
    embedded_metadata = storage.write_object(
        embedded_key,
        embedded.model_dump_json().encode(),
        content_type="application/json",
    )
    return EmbeddedArtifact(
        document=embedded,
        object_key=embedded_key,
        storage_version=embedded_metadata.version,
    )


class RecordingVectorIndex:
    def __init__(self) -> None:
        self.documents = []

    def replace_document(self, document):
        self.documents.append(document)
        return IndexWriteResult(
            document_id=document.document_id,
            chunk_count=len(document.chunks),
            embedding_config_hash=document.embedding_config_hash,
        )


def test_index_stage_combines_exact_chunk_text_with_embeddings():
    storage = FakeObjectStorage()
    artifact = stored_artifacts(storage, "first text", "second text")
    vector_index = RecordingVectorIndex()

    indexed = IndexStage(vector_index, storage).execute(artifact)

    assert indexed.document_id == artifact.document.document_id
    assert indexed.chunk_count == 2
    written = vector_index.documents[0]
    assert [chunk.text for chunk in written.chunks] == ["first text", "second text"]
    assert [chunk.chunk_id for chunk in written.chunks] == [
        embedding.chunk_id for embedding in artifact.document.embeddings
    ]
    assert written.source_object_key == artifact.object_key
    assert written.source_storage_version == artifact.storage_version


def test_index_stage_rejects_corrupt_embedded_artifact():
    storage = FakeObjectStorage()
    artifact = stored_artifacts(storage, "text")
    storage.object_contents[artifact.object_key] = b"not-json"

    with pytest.raises(IndexingError) as raised:
        IndexStage(RecordingVectorIndex(), storage).execute(artifact)

    assert raised.value.code == "INDEX_INPUT_INVALID"


def test_index_stage_rejects_embedding_and_chunk_provenance_mismatch():
    storage = FakeObjectStorage()
    artifact = stored_artifacts(storage, "text")
    chunked_key = artifact.document.source_chunked_object_key
    chunked = ChunkedDocument.model_validate_json(storage.object_contents[chunked_key])
    mismatched_chunk = chunked.chunks[0].model_copy(update={"content_hash": "f" * 64})
    mismatched = chunked.model_copy(update={"chunks": (mismatched_chunk,)})
    storage.object_contents[chunked_key] = mismatched.model_dump_json().encode()

    with pytest.raises(IndexingError) as raised:
        IndexStage(RecordingVectorIndex(), storage).execute(artifact)

    assert raised.value.code == "INDEX_PROVENANCE_MISMATCH"


def test_index_stage_rejects_tampered_embedding_configuration_hash():
    storage = FakeObjectStorage()
    artifact = stored_artifacts(storage, "text")
    tampered_document = artifact.document.model_copy(
        update={"configuration_hash": "f" * 64}
    )
    storage.object_contents[artifact.object_key] = (
        tampered_document.model_dump_json().encode()
    )
    tampered_artifact = EmbeddedArtifact(
        document=tampered_document,
        object_key=artifact.object_key,
        storage_version=artifact.storage_version,
    )

    with pytest.raises(IndexingError) as raised:
        IndexStage(RecordingVectorIndex(), storage).execute(tampered_artifact)

    assert raised.value.code == "INDEX_PROVENANCE_MISMATCH"


def add_document(factory):
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    with factory() as db, db.begin():
        user = User(username=f"user-{uuid4()}", password_hash="hash", is_active=True)
        db.add(user)
        db.flush()
        workspace = Workspace(name="Workspace", owner_user_id=user.id)
        db.add(workspace)
        db.flush()
        knowledge_base = KnowledgeBase(name="Knowledge", workspace_id=workspace.id)
        db.add(knowledge_base)
        db.flush()
        document = Document(
            knowledge_base_id=knowledge_base.id,
            uploaded_by_user_id=user.id,
            original_filename="notes.txt",
            declared_content_type="text/plain",
            declared_size_bytes=4,
            stored_size_bytes=4,
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
        return document.id, knowledge_base.id, workspace.id


def index_document(document_id, *texts, config_hash="a" * 64):
    return IndexDocument(
        document_id=document_id,
        embedding_provider="vertex-ai",
        embedding_model="gemini-embedding-001",
        embedding_dimensions=768,
        embedding_config_hash=config_hash,
        source_object_key="embedded.json",
        source_storage_version="7",
        chunks=tuple(
            IndexChunk(
                chunk_id=uuid4(),
                chunk_index=index,
                text=text,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                vector=tuple([float(index + 1)] * 768),
            )
            for index, text in enumerate(texts)
        ),
    )


def test_pgvector_index_is_atomic_idempotent_and_removes_stale_rows(
    indexing_database,
):
    document_id, knowledge_base_id, workspace_id = add_document(indexing_database)
    original = index_document(document_id, "first", "stale")
    vector_index = PgVectorIndex(indexing_database)

    first_result = vector_index.replace_document(original)
    repeated_result = vector_index.replace_document(original)

    assert first_result.chunk_count == 2
    assert repeated_result == first_result
    with indexing_database() as db:
        rows = db.scalars(select(IndexedChunk).order_by(IndexedChunk.chunk_index)).all()
        assert len(rows) == 2
        assert rows[0].workspace_id == workspace_id
        assert rows[0].knowledge_base_id == knowledge_base_id
        assert rows[0].chunk_text == "first"
        assert rows[0].embedding == [1.0] * 768

    replacement_chunk = IndexChunk(
        chunk_id=original.chunks[0].chunk_id,
        chunk_index=0,
        text="updated",
        content_hash=hashlib.sha256(b"updated").hexdigest(),
        vector=tuple([0.25] * 768),
    )
    replacement = IndexDocument(
        **{
            **original.__dict__,
            "chunks": (replacement_chunk,),
        }
    )
    vector_index.replace_document(replacement)

    with indexing_database() as db:
        rows = db.scalars(select(IndexedChunk)).all()
        assert len(rows) == 1
        assert rows[0].chunk_id == replacement_chunk.chunk_id
        assert rows[0].chunk_text == "updated"
        assert rows[0].embedding == [0.25] * 768


def test_pgvector_index_replaces_vectors_from_an_old_configuration(
    indexing_database,
):
    document_id, _, _ = add_document(indexing_database)
    vector_index = PgVectorIndex(indexing_database)
    old = index_document(document_id, "old", config_hash="a" * 64)
    new = index_document(document_id, "new", config_hash="b" * 64)

    vector_index.replace_document(old)
    vector_index.replace_document(new)

    with indexing_database() as db:
        rows = db.scalars(select(IndexedChunk)).all()
        assert len(rows) == 1
        assert rows[0].embedding_config_hash == "b" * 64
        assert rows[0].chunk_text == "new"


def test_pgvector_index_rejects_wrong_dimensions_before_writing(
    indexing_database,
):
    document_id, _, _ = add_document(indexing_database)
    document = index_document(document_id, "text")
    invalid = IndexDocument(**{**document.__dict__, "embedding_dimensions": 3})

    with pytest.raises(IndexingError) as raised:
        PgVectorIndex(indexing_database).replace_document(invalid)

    assert raised.value.code == "INDEX_DIMENSION_MISMATCH"


def test_pgvector_index_classifies_database_outage_as_transient():
    def unavailable_factory():
        raise OperationalError("unavailable", {}, Exception("secret database error"))

    document = index_document(uuid4(), "private chunk text")

    with pytest.raises(IndexingTransientError) as raised:
        PgVectorIndex(unavailable_factory).replace_document(document)

    assert raised.value.code == "INDEX_DATABASE_UNAVAILABLE"
    assert "private chunk text" not in str(raised.value)
    assert "secret database error" not in str(raised.value)
