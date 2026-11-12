import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.ingestion import (
    ChunkStage,
    DeliveryOutcome,
    EmbedStage,
    GraphStoreStage,
    HandleDisposition,
    IndexStage,
    IngestionJobClaimer,
    IngestionPipeline,
    IngestionRequestedMessage,
    IngestionWorker,
    NormalizeStage,
    ParseStage,
    PipelineDisposition,
    RelationExtractStage,
    SourceValidationError,
    SourceValidator,
)
from backend.ingestion.chunking import BlockAwareChunker, ChunkingError
from backend.ingestion.embedding import (
    DocumentEmbedder,
    EmbeddingError,
    EmbeddingTransientError,
)
from backend.ingestion.graph_storage import (
    GraphStorageError,
    GraphStorageTransientError,
    PostgresGraphStore,
)
from backend.ingestion.indexing import (
    IndexingError,
    IndexingTransientError,
    PgVectorIndex,
)
from backend.ingestion.normalization import DeterministicNormalizer
from backend.ingestion.parsing import ParserRegistry, PlainTextParser
from backend.ingestion.relation_extraction import (
    CandidateChunkExtraction,
    CandidateEntity,
    CandidateRelation,
    DocumentRelationExtractor,
    RelationExtractionError,
    RelationExtractionTransientError,
)
from backend.models import (
    Base,
    Document,
    Entity,
    EntityRelationship,
    IndexedChunk,
    IngestionJob,
    IngestionJobAttempt,
    KnowledgeBase,
    OutboxEvent,
    User,
    Workspace,
)
from backend.object_storage import ObjectStorageUnavailableError
from backend.object_storage.fake import FakeObjectStorage
from backend.object_storage.schemas import StoredObjectMetadata


@pytest.fixture
def ingestion_database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def add_queued_job(factory, now: datetime, *, size: int):
    with factory() as db:
        user = User(username="source-owner", password_hash="hash", is_active=True)
        db.add(user)
        db.flush()
        workspace = Workspace(name="Source", owner_user_id=user.id)
        db.add(workspace)
        db.flush()
        knowledge_base = KnowledgeBase(name="Documents", workspace_id=workspace.id)
        db.add(knowledge_base)
        db.flush()
        document = Document(
            knowledge_base_id=knowledge_base.id,
            uploaded_by_user_id=user.id,
            original_filename="notes.pdf",
            declared_content_type="application/pdf",
            declared_size_bytes=size,
            stored_size_bytes=size,
            storage_provider="gcs",
            storage_bucket="documents",
            storage_object_key=f"documents/{uuid4()}/original",
            storage_version="123",
            storage_checksum="checksum",
            storage_checksum_algorithm="crc32c",
            upload_status="STORED",
            processing_status="QUEUED",
            upload_expires_at=now + timedelta(minutes=10),
            uploaded_at=now,
        )
        db.add(document)
        db.flush()
        job = IngestionJob(
            document_id=document.id,
            idempotency_key=uuid4().hex,
            purpose="INITIAL_INGESTION",
            pipeline_version="v1",
            source_storage_version="123",
            status="QUEUED",
            attempt_count=0,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        return document, job


def envelope(job: IngestionJob, document: Document) -> bytes:
    value = {
        "event_id": str(uuid4()),
        "event_type": "document.ingestion.requested",
        "aggregate_type": "INGESTION_JOB",
        "aggregate_id": str(job.id),
        "schema_version": 1,
        "occurred_at": "2026-10-31T10:00:00+00:00",
        "data": {
            "job_id": str(job.id),
            "document_id": str(document.id),
            "purpose": job.purpose,
        },
    }
    return json.dumps(value).encode()


def configured_storage(document: Document, content: bytes) -> FakeObjectStorage:
    storage = FakeObjectStorage(provider="gcs", bucket="documents")
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="application/pdf",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    storage.object_contents[document.storage_object_key] = content
    return storage


def add_text_job(factory, now, content, *, storage=None):
    document, job = add_queued_job(factory, now, size=len(content))
    with factory() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
    storage = storage or configured_storage(document, content)
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    storage.object_contents[document.storage_object_key] = content
    return document, job, storage


def claim(factory, document, job, now):
    incoming = IngestionRequestedMessage.from_body(envelope(job, document))
    result = IngestionJobClaimer(factory, clock=lambda: now).claim(
        incoming,
        worker_id="worker-1",
    )
    assert result.claimed is not None
    return result.claimed


class PipelineEmbeddingProvider:
    provider_name = "fake"
    model_name = "fake-embedding-v1"
    dimensions = 3

    def __init__(self, error=None):
        self.error = error

    def embed(self, texts):
        if self.error is not None:
            raise self.error
        return tuple((float(len(text)), 1.0, 0.5) for text in texts)


def full_embedding_worker(factory, now, storage, provider):
    return IngestionWorker(
        IngestionJobClaimer(factory, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            factory,
            SourceValidator(factory, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            ChunkStage(BlockAwareChunker(), storage),
            EmbedStage(DocumentEmbedder(provider, batch_size=2), storage),
            clock=lambda: now,
        ),
    )


class PipelineIndexingProvider(PipelineEmbeddingProvider):
    dimensions = 768

    def embed(self, texts):
        if self.error is not None:
            raise self.error
        return tuple((float(len(text)), 1.0, *([0.5] * 766)) for text in texts)


class FailingVectorIndex:
    def __init__(self, error):
        self.error = error

    def replace_document(self, document):
        raise self.error


def full_indexing_worker(factory, now, storage, *, vector_index=None):
    return IngestionWorker(
        IngestionJobClaimer(factory, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            factory,
            SourceValidator(factory, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            ChunkStage(BlockAwareChunker(), storage),
            EmbedStage(
                DocumentEmbedder(PipelineIndexingProvider(), batch_size=2),
                storage,
            ),
            IndexStage(vector_index or PgVectorIndex(factory), storage),
            clock=lambda: now,
        ),
    )


class PipelineRelationProvider:
    provider_name = "fake"
    model_name = "fake-relations-v1"

    def __init__(self, error=None):
        self.error = error

    def extract(self, text, *, allowed_entity_types, allowed_relation_types):
        if self.error is not None:
            raise self.error
        return CandidateChunkExtraction(
            entities=(
                CandidateEntity(name="Sanjay", type="PERSON"),
                CandidateEntity(name="MedulaAPI", type="PROJECT"),
            ),
            relations=(
                CandidateRelation(
                    source_entity_index=0,
                    target_entity_index=1,
                    type="CREATED",
                    evidence="Sanjay created MedulaAPI",
                    confidence=0.98,
                ),
            ),
        )


def full_relation_worker(factory, now, storage, provider):
    return IngestionWorker(
        IngestionJobClaimer(factory, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            factory,
            SourceValidator(factory, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            ChunkStage(BlockAwareChunker(), storage),
            EmbedStage(
                DocumentEmbedder(PipelineIndexingProvider(), batch_size=2),
                storage,
            ),
            IndexStage(PgVectorIndex(factory), storage),
            RelationExtractStage(DocumentRelationExtractor(provider), storage),
            clock=lambda: now,
        ),
    )


class FailingGraphStore:
    def __init__(self, error):
        self.error = error

    def write(self, document):
        raise self.error


def full_graph_worker(factory, now, storage, provider, *, graph_store=None):
    return IngestionWorker(
        IngestionJobClaimer(factory, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            factory,
            SourceValidator(factory, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            ChunkStage(BlockAwareChunker(), storage),
            EmbedStage(
                DocumentEmbedder(PipelineIndexingProvider(), batch_size=2),
                storage,
            ),
            IndexStage(PgVectorIndex(factory), storage),
            RelationExtractStage(DocumentRelationExtractor(provider), storage),
            GraphStoreStage(graph_store or PostgresGraphStore(factory), storage),
            clock=lambda: now,
        ),
    )


def test_validate_source_downloads_the_claimed_immutable_object(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    content = b"%PDF-1.7\nsource document"
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    storage = configured_storage(document, content)
    claimed = claim(ingestion_database, document, job, now)

    result = IngestionPipeline(
        ingestion_database,
        SourceValidator(ingestion_database, storage),
        clock=lambda: now,
    ).process(claimed)

    assert result.disposition is PipelineDisposition.SOURCE_VALIDATED
    assert result.source is not None
    assert result.source.content == content
    assert result.source.storage_version == "123"


@pytest.mark.parametrize(
    "content,error_code",
    [
        (b"not a pdf document", "SOURCE_SIGNATURE_INVALID"),
        (b"", "SOURCE_EMPTY"),
    ],
)
def test_validate_source_rejects_invalid_bytes(
    ingestion_database,
    content,
    error_code,
):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    declared_size = max(1, len(content))
    document, job = add_queued_job(
        ingestion_database,
        now,
        size=declared_size,
    )
    storage = configured_storage(document, content)
    claimed = claim(ingestion_database, document, job, now)

    with pytest.raises(SourceValidationError) as raised:
        SourceValidator(ingestion_database, storage).validate(claimed)

    assert raised.value.code == error_code


def test_worker_records_source_rejection_before_acknowledging(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    content = b"not a pdf document"
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    storage = configured_storage(document, content)
    pipeline = IngestionPipeline(
        ingestion_database,
        SourceValidator(ingestion_database, storage),
        clock=lambda: now,
    )
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=pipeline,
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_SOURCE_REJECTED
    assert result.reason == "SOURCE_SIGNATURE_INVALID"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.status == "FAILED"
        assert saved_job.last_error_code == "SOURCE_SIGNATURE_INVALID"
        assert saved_job.claimed_by is None
        assert saved_document.processing_status == "REJECTED"
        assert saved_document.failure_code == "SOURCE_SIGNATURE_INVALID"
        assert attempt.status == "FAILED"
        assert attempt.failure_class == "PERMANENT"
        assert attempt.failure_code == "SOURCE_SIGNATURE_INVALID"


def test_worker_keeps_valid_source_unacknowledged_for_parse(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    content = b"%PDF-1.7\nsource document"
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    storage = configured_storage(document, content)
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            clock=lambda: now,
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.SOURCE_VALIDATED
    assert result.source is not None
    assert result.source.content == content
    assert result.delivery_outcome is DeliveryOutcome.LEAVE_UNSETTLED


def test_worker_parses_uploads_and_records_artifact_before_normalize(
    ingestion_database,
):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    content = b"First paragraph.\n\nSecond paragraph."
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    with ingestion_database() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
    storage = configured_storage(document, content)
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            clock=lambda: now,
        ),
    )
    result = worker.handle(envelope(job, document))

    expected_key = f"documents/{document.id}/parsed/123.json"
    assert result.disposition is HandleDisposition.PARSED
    assert result.parsed_artifact is not None
    assert result.parsed_artifact.object_key == expected_key
    assert b'"First paragraph."' in storage.object_contents[expected_key]
    assert result.delivery_outcome is DeliveryOutcome.LEAVE_UNSETTLED
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_document.parsed_storage_object_key == expected_key
        assert saved_document.parsed_storage_version == "1"
        assert saved_job.current_stage == "NORMALIZE"
        assert attempt.current_stage == "NORMALIZE"


def test_worker_schedules_retry_for_temporary_parsed_artifact_upload_failure(
    ingestion_database,
):
    class UnavailableStorage(FakeObjectStorage):
        def write_object(self, object_key, content, *, content_type):
            raise ObjectStorageUnavailableError("GCS temporarily unavailable")

    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    content = b"Retry this document."
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    with ingestion_database() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
    storage = UnavailableStorage(provider="gcs", bucket="documents")
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    storage.object_contents[document.storage_object_key] = content
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            clock=lambda: now,
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED
    assert result.reason == "PARSED_ARTIFACT_UPLOAD_FAILED"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        retry_event = db.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id)
        )
        assert saved_job.status == "RETRY_SCHEDULED"
        assert saved_job.current_stage == "PARSE"
        assert saved_job.next_attempt_at.replace(tzinfo=UTC) == now + timedelta(
            seconds=5
        )
        assert attempt.status == "FAILED"
        assert attempt.failure_class == "TRANSIENT"
        assert attempt.failure_code == "PARSED_ARTIFACT_UPLOAD_FAILED"
        assert retry_event is not None
        assert retry_event.available_at.replace(tzinfo=UTC) == now + timedelta(
            seconds=5
        )
        assert retry_event.payload == {
            "job_id": str(job.id),
            "document_id": str(document.id),
            "purpose": "INITIAL_INGESTION",
        }


def test_worker_exhausts_transient_failure_without_scheduling_another_event(
    ingestion_database,
):
    class UnavailableStorage(FakeObjectStorage):
        def write_object(self, object_key, content, *, content_type):
            raise ObjectStorageUnavailableError("GCS temporarily unavailable")

    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    content = b"Do not retry this document again."
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    with ingestion_database() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
        db.get(IngestionJob, job.id).max_attempts = 1
    storage = UnavailableStorage(provider="gcs", bucket="documents")
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    storage.object_contents[document.storage_object_key] = content
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            clock=lambda: now,
        ),
    )

    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_EXHAUSTED
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        assert saved_job.status == "FAILED"
        assert saved_job.next_attempt_at is None
        assert saved_document.processing_status == "FAILED"
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 0


def test_worker_normalizes_uploads_and_advances_to_chunk(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    content = "  Café\u00a0 value  ".encode()
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    with ingestion_database() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
    storage = configured_storage(document, content)
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            clock=lambda: now,
        ),
    )
    result = worker.handle(envelope(job, document))

    expected_key = f"documents/{document.id}/normalized/123/deterministic-v1.json"
    assert result.disposition is HandleDisposition.NORMALIZED
    assert result.normalized_artifact is not None
    assert result.normalized_artifact.object_key == expected_key
    assert result.normalized_artifact.document.blocks[0].text == "Café value"
    assert result.delivery_outcome is DeliveryOutcome.LEAVE_UNSETTLED
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_document.normalized_storage_object_key == expected_key
        assert saved_document.normalized_storage_version == "1"
        assert saved_job.current_stage == "CHUNK"
        assert attempt.current_stage == "CHUNK"


def test_worker_chunks_uploads_and_advances_to_embed(ingestion_database):
    now = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    content = b"First paragraph.\n\nSecond paragraph for chunking."
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    with ingestion_database() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
    storage = configured_storage(document, content)
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            ChunkStage(BlockAwareChunker(), storage),
            clock=lambda: now,
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.CHUNKED
    assert result.chunked_artifact is not None
    assert result.chunked_artifact.object_key.startswith(
        f"documents/{document.id}/chunked/1/block-aware-v1-"
    )
    assert result.chunked_artifact.document.chunks[0].text == (
        "First paragraph.\n\nSecond paragraph for chunking."
    )
    assert result.delivery_outcome is DeliveryOutcome.LEAVE_UNSETTLED
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert (
            saved_document.chunked_storage_object_key
            == result.chunked_artifact.object_key
        )
        assert saved_document.chunked_storage_version == "1"
        assert saved_job.current_stage == "EMBED"
        assert attempt.current_stage == "EMBED"


def test_worker_embeds_uploads_and_advances_to_index(ingestion_database):
    now = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
    content = b"First paragraph.\n\nSecond paragraph for embedding."
    document, job, storage = add_text_job(
        ingestion_database,
        now,
        content,
    )
    worker = full_embedding_worker(
        ingestion_database,
        now,
        storage,
        PipelineEmbeddingProvider(),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.EMBEDDED
    assert result.embedded_artifact is not None
    assert result.embedded_artifact.object_key.startswith(
        f"documents/{document.id}/embedded/1/fake-fake-embedding-v1-"
    )
    assert len(result.embedded_artifact.document.embeddings) == len(
        result.chunked_artifact.document.chunks
    )
    assert result.delivery_outcome is DeliveryOutcome.LEAVE_UNSETTLED
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert (
            saved_document.embedded_storage_object_key
            == result.embedded_artifact.object_key
        )
        assert saved_document.embedded_storage_version == "1"
        assert saved_job.current_stage == "INDEX"
        assert attempt.current_stage == "INDEX"


def test_worker_indexes_chunks_and_advances_to_relation_extraction(
    ingestion_database,
):
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    content = b"First paragraph.\n\nSecond paragraph for vector indexing."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_indexing_worker(ingestion_database, now, storage)
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.INDEXED
    assert result.indexed_artifact is not None
    assert result.indexed_artifact.document_id == document.id
    assert result.indexed_artifact.chunk_count == 1
    assert result.delivery_outcome is DeliveryOutcome.LEAVE_UNSETTLED
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        indexed = db.scalar(
            select(IndexedChunk).where(IndexedChunk.document_id == document.id)
        )
        assert saved_job.current_stage == "RELATION_EXTRACT"
        assert attempt.current_stage == "RELATION_EXTRACT"
        assert indexed.chunk_text == content.decode()
        assert indexed.embedding_dimensions == 768
        assert len(indexed.embedding) == 768


def test_worker_extracts_relations_and_advances_to_graph_store(ingestion_database):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    content = b"Sanjay created MedulaAPI."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_relation_worker(
        ingestion_database,
        now,
        storage,
        PipelineRelationProvider(),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.RELATIONS_EXTRACTED
    assert result.relations_artifact is not None
    assert result.relations_artifact.document.document_id == document.id
    assert result.relations_artifact.document.statistics.relation_count == 1
    assert result.delivery_outcome is DeliveryOutcome.LEAVE_UNSETTLED
    stored = json.loads(storage.object_contents[result.relations_artifact.object_key])
    assert stored["chunks"][0]["relations"][0]["type"] == "CREATED"
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_document.relations_storage_object_key == (
            result.relations_artifact.object_key
        )
        assert saved_document.relations_storage_version == "1"
        assert saved_job.current_stage == "GRAPH_STORE"
        assert attempt.current_stage == "GRAPH_STORE"


def test_worker_stores_graph_and_completes_ingestion(ingestion_database):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    content = b"Sanjay created MedulaAPI."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_graph_worker(
        ingestion_database,
        now,
        storage,
        PipelineRelationProvider(),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.GRAPH_STORED
    assert result.graph_write_result is not None
    assert result.graph_write_result.entity_count == 2
    assert result.graph_write_result.relationship_count == 1
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        relationship = db.scalar(select(EntityRelationship))
        assert db.scalar(select(func.count()).select_from(Entity)) == 2
        assert relationship.document_id == document.id
        assert saved_job.status == "SUCCEEDED"
        assert saved_job.current_stage == "COMPLETE"
        assert saved_document.processing_status == "READY"
        assert saved_document.processed_at.replace(tzinfo=UTC) == now
        assert attempt.status == "SUCCEEDED"
        assert attempt.current_stage == "COMPLETE"


def test_worker_schedules_retry_for_transient_graph_storage_failure(ingestion_database):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    content = b"Sanjay created MedulaAPI."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_graph_worker(
        ingestion_database,
        now,
        storage,
        PipelineRelationProvider(),
        graph_store=FailingGraphStore(
            GraphStorageTransientError(
                "GRAPH_DATABASE_UNAVAILABLE",
                "The graph database is unavailable.",
            )
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED
    assert result.reason == "GRAPH_DATABASE_UNAVAILABLE"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.status == "RETRY_SCHEDULED"
        assert saved_job.current_stage == "GRAPH_STORE"
        assert attempt.current_stage == "GRAPH_STORE"


def test_worker_records_permanent_graph_storage_failure(ingestion_database):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    content = b"Sanjay created MedulaAPI."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_graph_worker(
        ingestion_database,
        now,
        storage,
        PipelineRelationProvider(),
        graph_store=FailingGraphStore(
            GraphStorageError(
                "GRAPH_WRITE_INVALID",
                "The resolved graph is invalid.",
            )
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_GRAPH_STORE_REJECTED
    assert result.reason == "GRAPH_WRITE_INVALID"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        assert saved_job.status == "FAILED"
        assert saved_document.processing_status == "REJECTED"


def test_worker_schedules_retry_for_transient_relation_provider_failure(
    ingestion_database,
):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    content = b"Sanjay created MedulaAPI."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_relation_worker(
        ingestion_database,
        now,
        storage,
        PipelineRelationProvider(
            RelationExtractionTransientError(
                "RELATION_PROVIDER_UNAVAILABLE",
                "The relation provider is temporarily unavailable.",
            )
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED
    assert result.reason == "RELATION_PROVIDER_UNAVAILABLE"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.status == "RETRY_SCHEDULED"
        assert saved_job.current_stage == "RELATION_EXTRACT"
        assert attempt.current_stage == "RELATION_EXTRACT"
        assert saved_document.relations_storage_object_key is None


def test_worker_records_permanent_relation_failure_before_acknowledging(
    ingestion_database,
):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    content = b"Sanjay created MedulaAPI."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_relation_worker(
        ingestion_database,
        now,
        storage,
        PipelineRelationProvider(
            RelationExtractionError(
                "RELATION_PROVIDER_OUTPUT_INVALID",
                "The relation provider returned malformed output.",
            )
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is (
        HandleDisposition.ACKNOWLEDGED_RELATION_EXTRACT_REJECTED
    )
    assert result.reason == "RELATION_PROVIDER_OUTPUT_INVALID"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        assert saved_job.status == "FAILED"
        assert saved_document.processing_status == "REJECTED"


def test_worker_schedules_retry_for_transient_index_failure(ingestion_database):
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    content = b"Retry vector indexing."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_indexing_worker(
        ingestion_database,
        now,
        storage,
        vector_index=FailingVectorIndex(
            IndexingTransientError(
                "INDEX_DATABASE_UNAVAILABLE",
                "The vector index is temporarily unavailable.",
            )
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED
    assert result.reason == "INDEX_DATABASE_UNAVAILABLE"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.status == "RETRY_SCHEDULED"
        assert saved_job.current_stage == "INDEX"
        assert attempt.current_stage == "INDEX"
        assert attempt.failure_class == "TRANSIENT"


def test_worker_schedules_retry_for_temporary_index_source_download_failure(
    ingestion_database,
):
    class IndexReadUnavailableStorage(FakeObjectStorage):
        def read_object(self, object_key, *, version=None):
            if "/embedded/" in object_key:
                raise ObjectStorageUnavailableError("GCS temporarily unavailable")
            return super().read_object(object_key, version=version)

    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    content = b"Retry vector-index source download."
    storage = IndexReadUnavailableStorage(provider="gcs", bucket="documents")
    document, job, storage = add_text_job(
        ingestion_database,
        now,
        content,
        storage=storage,
    )
    worker = full_indexing_worker(ingestion_database, now, storage)
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED
    assert result.reason == "INDEX_SOURCE_ARTIFACT_UNAVAILABLE"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.current_stage == "INDEX"
        assert attempt.current_stage == "INDEX"
        assert attempt.failure_code == "INDEX_SOURCE_ARTIFACT_UNAVAILABLE"


def test_worker_acknowledges_permanent_index_rejection(ingestion_database):
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    content = b"Reject vector indexing."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_indexing_worker(
        ingestion_database,
        now,
        storage,
        vector_index=FailingVectorIndex(
            IndexingError(
                "INDEX_PROVENANCE_MISMATCH",
                "The indexing provenance is invalid.",
            )
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_INDEX_REJECTED
    assert result.reason == "INDEX_PROVENANCE_MISMATCH"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.status == "FAILED"
        assert saved_document.processing_status == "REJECTED"
        assert saved_document.failure_code == "INDEX_PROVENANCE_MISMATCH"
        assert attempt.failure_class == "PERMANENT"


def test_worker_schedules_retry_for_transient_embedding_provider_failure(
    ingestion_database,
):
    now = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
    content = b"Retry embedding."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_embedding_worker(
        ingestion_database,
        now,
        storage,
        PipelineEmbeddingProvider(
            EmbeddingTransientError(
                "EMBED_PROVIDER_RATE_LIMITED",
                "The embedding provider rate limit was reached.",
            )
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED
    assert result.reason == "EMBED_PROVIDER_RATE_LIMITED"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.status == "RETRY_SCHEDULED"
        assert saved_job.current_stage == "EMBED"
        assert attempt.current_stage == "EMBED"
        assert attempt.failure_class == "TRANSIENT"
        assert attempt.failure_code == "EMBED_PROVIDER_RATE_LIMITED"


def test_worker_acknowledges_permanent_embedding_rejection(ingestion_database):
    now = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
    content = b"Reject embedding."
    document, job, storage = add_text_job(ingestion_database, now, content)
    worker = full_embedding_worker(
        ingestion_database,
        now,
        storage,
        PipelineEmbeddingProvider(
            EmbeddingError(
                "EMBED_PROVIDER_OUTPUT_INVALID",
                "The embedding provider returned malformed output.",
            )
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_EMBED_REJECTED
    assert result.reason == "EMBED_PROVIDER_OUTPUT_INVALID"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.status == "FAILED"
        assert saved_document.processing_status == "REJECTED"
        assert saved_document.failure_code == "EMBED_PROVIDER_OUTPUT_INVALID"
        assert attempt.failure_class == "PERMANENT"


def test_worker_schedules_retry_for_temporary_embedded_artifact_upload_failure(
    ingestion_database,
):
    class EmbeddedUploadUnavailableStorage(FakeObjectStorage):
        def write_object(self, object_key, content, *, content_type):
            if "/embedded/" in object_key:
                raise ObjectStorageUnavailableError("GCS temporarily unavailable")
            return super().write_object(
                object_key,
                content,
                content_type=content_type,
            )

    now = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
    content = b"Retry embedded artifact upload."
    storage = EmbeddedUploadUnavailableStorage(provider="gcs", bucket="documents")
    document, job, storage = add_text_job(
        ingestion_database,
        now,
        content,
        storage=storage,
    )
    worker = full_embedding_worker(
        ingestion_database,
        now,
        storage,
        PipelineEmbeddingProvider(),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED
    assert result.reason == "EMBEDDED_ARTIFACT_UPLOAD_FAILED"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.current_stage == "EMBED"
        assert attempt.current_stage == "EMBED"
        assert attempt.failure_class == "TRANSIENT"
        assert attempt.failure_code == "EMBEDDED_ARTIFACT_UPLOAD_FAILED"


def test_worker_schedules_retry_for_temporary_chunked_artifact_upload_failure(
    ingestion_database,
):
    class ChunkedUploadUnavailableStorage(FakeObjectStorage):
        def write_object(self, object_key, content, *, content_type):
            if "/chunked/" in object_key:
                raise ObjectStorageUnavailableError("GCS temporarily unavailable")
            return super().write_object(
                object_key,
                content,
                content_type=content_type,
            )

    now = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    content = b"Retry chunking."
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    with ingestion_database() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
    storage = ChunkedUploadUnavailableStorage(provider="gcs", bucket="documents")
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    storage.object_contents[document.storage_object_key] = content
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            ChunkStage(BlockAwareChunker(), storage),
            clock=lambda: now,
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED
    assert result.reason == "CHUNKED_ARTIFACT_UPLOAD_FAILED"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.current_stage == "CHUNK"
        assert attempt.current_stage == "CHUNK"
        assert attempt.failure_code == "CHUNKED_ARTIFACT_UPLOAD_FAILED"


def test_worker_acknowledges_permanent_chunking_rejection(ingestion_database):
    class RejectingChunker:
        @property
        def name(self):
            return "rejecting"

        @property
        def version(self):
            return "1"

        def chunk(
            self,
            document,
            *,
            source_object_key,
            source_storage_version,
        ):
            raise ChunkingError(
                "CHUNK_PROVENANCE_INVALID",
                "Normalized provenance is invalid.",
            )

    now = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    content = b"Reject chunking."
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    with ingestion_database() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
    storage = configured_storage(document, content)
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            ChunkStage(RejectingChunker(), storage),
            clock=lambda: now,
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_CHUNK_REJECTED
    assert result.reason == "CHUNK_PROVENANCE_INVALID"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        assert saved_job.status == "FAILED"
        assert saved_document.processing_status == "REJECTED"
        assert saved_document.failure_code == "CHUNK_PROVENANCE_INVALID"


def test_worker_schedules_retry_for_temporary_normalized_artifact_upload_failure(
    ingestion_database,
):
    class NormalizedUploadUnavailableStorage(FakeObjectStorage):
        def write_object(self, object_key, content, *, content_type):
            if "/normalized/" in object_key:
                raise ObjectStorageUnavailableError("GCS temporarily unavailable")
            return super().write_object(
                object_key,
                content,
                content_type=content_type,
            )

    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    content = b"Retry normalization."
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    with ingestion_database() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
    storage = NormalizedUploadUnavailableStorage(
        provider="gcs",
        bucket="documents",
    )
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    storage.object_contents[document.storage_object_key] = content
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            clock=lambda: now,
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_RETRY_SCHEDULED
    assert result.reason == "NORMALIZED_ARTIFACT_UPLOAD_FAILED"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.current_stage == "NORMALIZE"
        assert attempt.current_stage == "NORMALIZE"
        assert attempt.failure_code == "NORMALIZED_ARTIFACT_UPLOAD_FAILED"


def test_worker_acknowledges_permanent_normalization_rejection(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    content = b"\x01"
    document, job = add_queued_job(ingestion_database, now, size=len(content))
    with ingestion_database() as db, db.begin():
        saved_document = db.get(Document, document.id)
        saved_document.original_filename = "notes.txt"
        saved_document.declared_content_type = "text/plain"
    storage = configured_storage(document, content)
    storage.objects[document.storage_object_key] = StoredObjectMetadata(
        size_bytes=len(content),
        content_type="text/plain",
        version="123",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
        pipeline=IngestionPipeline(
            ingestion_database,
            SourceValidator(ingestion_database, storage),
            ParseStage(ParserRegistry([PlainTextParser()]), storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            clock=lambda: now,
        ),
    )
    result = worker.handle(envelope(job, document))

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_NORMALIZE_REJECTED
    assert result.reason == "NORMALIZE_NO_TEXT"
    assert result.delivery_outcome is DeliveryOutcome.ACKNOWLEDGE
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        assert saved_job.status == "FAILED"
        assert saved_document.processing_status == "REJECTED"
        assert saved_document.failure_code == "NORMALIZE_NO_TEXT"
