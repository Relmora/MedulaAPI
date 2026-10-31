import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.ingestion import (
    ClaimDisposition,
    HandleDisposition,
    IngestionJobClaimer,
    IngestionRequestedMessage,
    IngestionWorker,
    InvalidMessage,
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


def add_queued_job(factory, now: datetime) -> tuple[Document, IngestionJob]:
    with factory() as db:
        user = User(username="worker-owner", password_hash="hash", is_active=True)
        db.add(user)
        db.flush()
        workspace = Workspace(name="Worker", owner_user_id=user.id)
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
            declared_size_bytes=100,
            stored_size_bytes=100,
            storage_provider="gcs",
            storage_bucket="documents",
            storage_object_key=f"documents/{uuid4()}/original",
            storage_version="1",
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
            source_storage_version="1",
            status="QUEUED",
            attempt_count=0,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        return document, job


def envelope(job: IngestionJob, document: Document) -> dict[str, object]:
    return {
        "event_id": str(uuid4()),
        "event_type": "document.ingestion.requested",
        "aggregate_type": "INGESTION_JOB",
        "aggregate_id": str(job.id),
        "schema_version": 1,
        "occurred_at": "2026-10-31T10:00:00+00:00",
        "data": {
            "job_id": str(job.id),
            "document_id": str(document.id),
            "purpose": "INITIAL_INGESTION",
        },
    }


def message(job: IngestionJob, document: Document) -> IngestionRequestedMessage:
    return IngestionRequestedMessage.from_body(json.dumps(envelope(job, document)).encode())


def test_message_matches_the_published_outbox_envelope(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    document, job = add_queued_job(ingestion_database, now)

    parsed = message(job, document)

    assert parsed.job_id == job.id
    assert parsed.document_id == document.id
    assert parsed.purpose == "INITIAL_INGESTION"


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(schema_version=2),
        lambda value: value.update(event_type="other.event"),
        lambda value: value.update(aggregate_id=str(uuid4())),
        lambda value: value["data"].update(document_id="not-a-uuid"),
    ],
)
def test_invalid_messages_are_rejected(ingestion_database, change):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    document, job = add_queued_job(ingestion_database, now)
    value = envelope(job, document)
    change(value)

    with pytest.raises(InvalidMessage):
        IngestionRequestedMessage.from_body(json.dumps(value).encode())


def test_claim_updates_job_document_and_attempt_in_one_commit(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    document, job = add_queued_job(ingestion_database, now)
    claimer = IngestionJobClaimer(
        ingestion_database,
        lease_ttl=timedelta(seconds=90),
        clock=lambda: now,
    )

    result = claimer.claim(message(job, document), worker_id="worker-1")

    assert result.disposition is ClaimDisposition.CLAIMED
    assert result.claimed is not None
    assert result.claimed.attempt_number == 1
    assert result.claimed.current_stage == "VALIDATE_SOURCE"
    assert result.claimed.lease_expires_at == now + timedelta(seconds=90)
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        attempt = db.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == job.id)
        )
        assert saved_job.status == "PROCESSING"
        assert saved_job.current_stage == "VALIDATE_SOURCE"
        assert saved_job.attempt_count == 1
        assert saved_job.claimed_by == "worker-1"
        assert saved_document.processing_status == "PROCESSING"
        assert attempt is not None
        assert attempt.id == result.claimed.attempt_id
        assert attempt.attempt_number == 1
        assert attempt.status == "RUNNING"
        assert attempt.worker_id == "worker-1"


def test_duplicate_delivery_does_not_create_another_attempt(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    document, job = add_queued_job(ingestion_database, now)
    claimer = IngestionJobClaimer(ingestion_database, clock=lambda: now)
    incoming = message(job, document)

    first = claimer.claim(incoming, worker_id="worker-1")
    duplicate = claimer.claim(incoming, worker_id="worker-2")

    assert first.disposition is ClaimDisposition.CLAIMED
    assert duplicate.disposition is ClaimDisposition.OBSOLETE
    assert duplicate.reason == "JOB_NOT_RUNNABLE"
    with ingestion_database() as db:
        assert db.get(IngestionJob, job.id).attempt_count == 1
        assert len(db.scalars(select(IngestionJobAttempt)).all()) == 1


def test_failed_attempt_insert_rolls_back_the_job_and_document(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    document, job = add_queued_job(ingestion_database, now)
    with ingestion_database() as db:
        db.add(
            IngestionJobAttempt(
                job_id=job.id,
                attempt_number=1,
                worker_id="existing-worker",
                status="RUNNING",
                current_stage="VALIDATE_SOURCE",
                started_at=now,
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=60),
            )
        )
        db.commit()

    claimer = IngestionJobClaimer(ingestion_database, clock=lambda: now)
    with pytest.raises(IntegrityError):
        claimer.claim(message(job, document), worker_id="worker-1")

    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_document = db.get(Document, document.id)
        assert saved_job.status == "QUEUED"
        assert saved_job.attempt_count == 0
        assert saved_job.claimed_by is None
        assert saved_document.processing_status == "QUEUED"


class RecordingDelivery:
    def __init__(self) -> None:
        self.acknowledged = False
        self.rejected_with: bool | None = None

    def acknowledge(self) -> None:
        self.acknowledged = True

    def reject(self, *, requeue: bool) -> None:
        self.rejected_with = requeue


def test_worker_leaves_successful_claim_unacknowledged(ingestion_database):
    now = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
    document, job = add_queued_job(ingestion_database, now)
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database, clock=lambda: now),
        worker_id="worker-1",
    )
    delivery = RecordingDelivery()

    result = worker.handle(json.dumps(envelope(job, document)).encode(), delivery)

    assert result.disposition is HandleDisposition.CLAIMED
    assert delivery.acknowledged is False
    assert delivery.rejected_with is None


def test_worker_rejects_invalid_message_without_requeue(ingestion_database):
    worker = IngestionWorker(
        IngestionJobClaimer(ingestion_database),
        worker_id="worker-1",
    )
    delivery = RecordingDelivery()

    result = worker.handle(b"not-json", delivery)

    assert result.disposition is HandleDisposition.REJECTED_INVALID
    assert delivery.acknowledged is False
    assert delivery.rejected_with is False
