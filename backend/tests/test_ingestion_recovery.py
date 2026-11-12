from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.ingestion.claim import ClaimedIngestionJob
from backend.ingestion.lease import IngestionLeaseHeartbeat
from backend.ingestion.recovery import LEASE_EXPIRED_CODE, IngestionLeaseRecovery
from backend.models import (
    Base,
    Document,
    IngestionJob,
    IngestionJobAttempt,
    KnowledgeBase,
    OutboxEvent,
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


def add_processing_job(
    factory,
    now: datetime,
    *,
    lease_expires_at: datetime,
    attempt_count: int = 1,
    max_attempts: int = 3,
) -> tuple[Document, IngestionJob, IngestionJobAttempt]:
    with factory() as db:
        user = User(username=f"owner-{uuid4()}", password_hash="hash", is_active=True)
        db.add(user)
        db.flush()
        workspace = Workspace(name="Recovery", owner_user_id=user.id)
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
            processing_status="PROCESSING",
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
            status="PROCESSING",
            current_stage="PARSE",
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            claimed_by="worker-1",
            lease_expires_at=lease_expires_at,
            started_at=now - timedelta(minutes=1),
        )
        db.add(job)
        db.flush()
        attempt = IngestionJobAttempt(
            job_id=job.id,
            attempt_number=attempt_count,
            worker_id="worker-1",
            status="RUNNING",
            current_stage="PARSE",
            started_at=now - timedelta(minutes=1),
            heartbeat_at=now - timedelta(minutes=1),
            lease_expires_at=lease_expires_at,
        )
        db.add(attempt)
        db.commit()
        return document, job, attempt


def test_expired_lease_is_abandoned_and_durably_retried(ingestion_database):
    now = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    document, job, attempt = add_processing_job(
        ingestion_database,
        now,
        lease_expires_at=now - timedelta(seconds=1),
    )
    recovery = IngestionLeaseRecovery(
        ingestion_database,
        clock=lambda: now,
        retry_delay=lambda _attempt: timedelta(seconds=10),
    )

    result = recovery.recover_batch()

    assert result.recovered == 1
    assert result.retries_scheduled == 1
    assert result.exhausted == 0
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_attempt = db.get(IngestionJobAttempt, attempt.id)
        saved_document = db.get(Document, document.id)
        retry_event = db.scalar(select(OutboxEvent))
        assert saved_attempt.status == "ABANDONED"
        assert saved_attempt.failure_class == "TRANSIENT"
        assert saved_attempt.failure_code == LEASE_EXPIRED_CODE
        assert saved_job.status == "RETRY_SCHEDULED"
        assert saved_job.next_attempt_at.replace(tzinfo=UTC) == now + timedelta(
            seconds=10
        )
        assert saved_job.claimed_by is None
        assert saved_job.lease_expires_at is None
        assert saved_document.processing_status == "QUEUED"
        assert retry_event.available_at.replace(tzinfo=UTC) == now + timedelta(
            seconds=10
        )
        assert retry_event.payload == {
            "job_id": str(job.id),
            "document_id": str(document.id),
            "purpose": "INITIAL_INGESTION",
        }

    assert recovery.recover_batch().recovered == 0
    with ingestion_database() as db:
        assert len(db.scalars(select(OutboxEvent)).all()) == 1


def test_expired_lease_fails_when_attempt_budget_is_exhausted(ingestion_database):
    now = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    document, job, attempt = add_processing_job(
        ingestion_database,
        now,
        lease_expires_at=now - timedelta(seconds=1),
        attempt_count=3,
        max_attempts=3,
    )

    result = IngestionLeaseRecovery(
        ingestion_database,
        clock=lambda: now,
    ).recover_batch()

    assert result.recovered == 1
    assert result.retries_scheduled == 0
    assert result.exhausted == 1
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_attempt = db.get(IngestionJobAttempt, attempt.id)
        saved_document = db.get(Document, document.id)
        assert saved_attempt.status == "ABANDONED"
        assert saved_job.status == "FAILED"
        assert saved_job.finished_at is not None
        assert saved_document.processing_status == "FAILED"
        assert db.scalar(select(OutboxEvent)) is None


def test_active_lease_is_not_recovered(ingestion_database):
    now = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    _, job, attempt = add_processing_job(
        ingestion_database,
        now,
        lease_expires_at=now + timedelta(seconds=1),
    )

    result = IngestionLeaseRecovery(
        ingestion_database,
        clock=lambda: now,
    ).recover_batch()

    assert result.recovered == 0
    with ingestion_database() as db:
        assert db.get(IngestionJob, job.id).status == "PROCESSING"
        assert db.get(IngestionJobAttempt, attempt.id).status == "RUNNING"


def test_heartbeat_renews_job_and_attempt_lease(ingestion_database):
    now = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
    _, job, attempt = add_processing_job(
        ingestion_database,
        now,
        lease_expires_at=now + timedelta(seconds=5),
    )
    claimed = ClaimedIngestionJob(
        job_id=job.id,
        document_id=job.document_id,
        attempt_id=attempt.id,
        attempt_number=1,
        worker_id="worker-1",
        current_stage="PARSE",
        lease_expires_at=now + timedelta(seconds=5),
        event_id=uuid4(),
    )

    renewed = IngestionLeaseHeartbeat(
        ingestion_database,
        lease_ttl=timedelta(seconds=90),
        clock=lambda: now,
    ).renew(claimed)

    assert renewed is True
    with ingestion_database() as db:
        saved_job = db.get(IngestionJob, job.id)
        saved_attempt = db.get(IngestionJobAttempt, attempt.id)
        assert saved_job.lease_expires_at.replace(tzinfo=UTC) == now + timedelta(
            seconds=90
        )
        assert saved_attempt.lease_expires_at.replace(tzinfo=UTC) == now + timedelta(
            seconds=90
        )
        assert saved_attempt.heartbeat_at.replace(tzinfo=UTC) == now
