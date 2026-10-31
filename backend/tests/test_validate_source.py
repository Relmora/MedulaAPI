import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.ingestion import (
    HandleDisposition,
    IngestionJobClaimer,
    IngestionPipeline,
    IngestionRequestedMessage,
    IngestionWorker,
    PipelineDisposition,
    SourceValidationError,
    SourceValidator,
)
from backend.models import (
    Base,
    Document,
    IngestionJob,
    IngestionJobAttempt,
    KnowledgeBase,
    User,
    Workspace,
)
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


def claim(factory, document, job, now):
    incoming = IngestionRequestedMessage.from_body(envelope(job, document))
    result = IngestionJobClaimer(factory, clock=lambda: now).claim(
        incoming,
        worker_id="worker-1",
    )
    assert result.claimed is not None
    return result.claimed


class RecordingDelivery:
    def __init__(self) -> None:
        self.acknowledged = False
        self.rejected_with = None

    def acknowledge(self) -> None:
        self.acknowledged = True

    def reject(self, *, requeue: bool) -> None:
        self.rejected_with = requeue


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
    delivery = RecordingDelivery()

    result = worker.handle(envelope(job, document), delivery)

    assert result.disposition is HandleDisposition.ACKNOWLEDGED_SOURCE_REJECTED
    assert result.reason == "SOURCE_SIGNATURE_INVALID"
    assert delivery.acknowledged is True
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
    delivery = RecordingDelivery()

    result = worker.handle(envelope(job, document), delivery)

    assert result.disposition is HandleDisposition.SOURCE_VALIDATED
    assert result.source is not None
    assert result.source.content == content
    assert delivery.acknowledged is False
    assert delivery.rejected_with is None
