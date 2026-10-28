from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_workspace_routes import clients as clients

from backend.documents.schemas import DocumentUploadIntentCreate
from backend.documents.service import (
    complete_document_upload,
    create_pending_document,
    get_document,
)
from backend.errors import AppError
from backend.models import Document, IngestionJob, OutboxEvent, User
from backend.object_storage.fake import FakeObjectStorage
from backend.object_storage.schemas import StoredObjectMetadata


def hierarchy(client) -> tuple[UUID, UUID]:
    workspace_id = client.post("/workspaces", json={"name": "Workspace"}).json()["id"]
    knowledge_base_id = client.post(
        f"/workspaces/{workspace_id}/knowledge-bases", json={"name": "Documents"}
    ).json()["id"]
    return UUID(workspace_id), UUID(knowledge_base_id)


def payload(filename: str = "notes.pdf") -> DocumentUploadIntentCreate:
    return DocumentUploadIntentCreate(
        original_filename=filename,
        declared_content_type="application/pdf",
        declared_size_bytes=1024,
    )


def users(db: Session) -> tuple[User, User]:
    return tuple(db.scalars(select(User).order_by(User.username)))


def test_create_pending_document_persists_upload_intent(clients):
    alice_client, _, engine = clients
    workspace_id, knowledge_base_id = hierarchy(alice_client)
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

    with Session(engine) as db:
        alice, _ = users(db)
        alice_id = alice.id
        storage = FakeObjectStorage(provider="gcs", bucket="documents-test")
        pending = create_pending_document(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            payload(),
            storage=storage,
            now=now,
        )
        document = pending.document
        db.commit()
        document_id = document.id

        assert pending.upload.method == "PUT"
        assert pending.upload.expires_at == now + timedelta(minutes=15)
        assert pending.upload.headers == {
            "Content-Type": "application/pdf",
            "X-Expected-Size": "1024",
        }
        assert storage.upload_requests[0].object_key == document.storage_object_key

    with Session(engine) as db:
        saved = db.get(Document, document_id)
        assert saved is not None
        assert saved.knowledge_base_id == knowledge_base_id
        assert saved.uploaded_by_user_id == alice_id
        assert saved.original_filename == "notes.pdf"
        assert saved.declared_content_type == "application/pdf"
        assert saved.declared_size_bytes == 1024
        assert saved.storage_provider == "gcs"
        assert saved.storage_bucket == "documents-test"
        assert saved.storage_object_key == f"documents/{document_id}/original"
        assert saved.upload_status == "PENDING"
        assert saved.processing_status == "NOT_QUEUED"
        assert saved.upload_expires_at.replace(tzinfo=UTC) == now + timedelta(
            minutes=15
        )
        assert saved.detected_content_type is None
        assert saved.stored_size_bytes is None
        assert saved.storage_version is None
        assert saved.storage_checksum is None
        assert saved.storage_checksum_algorithm is None
        assert saved.uploaded_at is None


def test_generated_object_keys_are_unique(clients):
    alice_client, _, engine = clients
    workspace_id, knowledge_base_id = hierarchy(alice_client)

    with Session(engine) as db:
        alice, _ = users(db)
        storage = FakeObjectStorage()
        first = create_pending_document(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            payload("first.pdf"),
            storage=storage,
        ).document
        second = create_pending_document(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            payload("second.pdf"),
            storage=storage,
        ).document
        assert first.id != second.id
        assert first.storage_object_key != second.storage_object_key


def test_create_and_get_are_owner_scoped(clients):
    alice_client, _, engine = clients
    workspace_id, knowledge_base_id = hierarchy(alice_client)

    with Session(engine) as db:
        alice, bob = users(db)
        storage = FakeObjectStorage()
        document = create_pending_document(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            payload(),
            storage=storage,
        ).document
        assert (
            get_document(db, alice, workspace_id, knowledge_base_id, document.id).id
            == document.id
        )
        for operation in (
            lambda: create_pending_document(
                db,
                bob,
                workspace_id,
                knowledge_base_id,
                payload(),
                storage=storage,
            ),
            lambda: get_document(db, bob, workspace_id, knowledge_base_id, document.id),
        ):
            with pytest.raises(AppError) as error:
                operation()
            assert error.value.code == "WORKSPACE_NOT_FOUND"
            assert error.value.status_code == 404


def test_document_must_belong_to_requested_knowledge_base(clients):
    alice_client, _, engine = clients
    workspace_id, knowledge_base_id = hierarchy(alice_client)
    other_knowledge_base_id = UUID(
        alice_client.post(
            f"/workspaces/{workspace_id}/knowledge-bases", json={"name": "Other"}
        ).json()["id"]
    )

    with Session(engine) as db:
        alice, _ = users(db)
        document = create_pending_document(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            payload(),
            storage=FakeObjectStorage(),
        ).document
        with pytest.raises(AppError) as error:
            get_document(
                db,
                alice,
                workspace_id,
                other_knowledge_base_id,
                document.id,
            )
        assert error.value.code == "DOCUMENT_NOT_FOUND"
        assert error.value.status_code == 404


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {},
        {
            "original_filename": "",
            "declared_content_type": "application/pdf",
            "declared_size_bytes": 1,
        },
        {
            "original_filename": "../notes.pdf",
            "declared_content_type": "application/pdf",
            "declared_size_bytes": 1,
        },
        {
            "original_filename": "notes.exe",
            "declared_content_type": "application/octet-stream",
            "declared_size_bytes": 1,
        },
        {
            "original_filename": "notes.pdf",
            "declared_content_type": "application/pdf",
            "declared_size_bytes": 0,
        },
        {
            "original_filename": "notes.pdf",
            "declared_content_type": "application/pdf",
            "declared_size_bytes": 1,
            "storage_object_key": "chosen/by/client",
        },
    ],
)
def test_upload_intent_rejects_untrusted_metadata(invalid_payload):
    with pytest.raises(ValidationError):
        DocumentUploadIntentCreate.model_validate(invalid_payload)


def test_upload_intent_normalizes_safe_metadata():
    result = DocumentUploadIntentCreate(
        original_filename=" notes.md ",
        declared_content_type=" Text/Markdown ",
        declared_size_bytes=12,
    )
    assert result.original_filename == "notes.md"
    assert result.declared_content_type == "text/markdown"


def test_internal_time_arguments_must_be_valid(clients):
    alice_client, _, engine = clients
    workspace_id, knowledge_base_id = hierarchy(alice_client)
    with Session(engine) as db:
        alice, _ = users(db)
        with pytest.raises(ValueError, match="timezone-aware"):
            create_pending_document(
                db,
                alice,
                workspace_id,
                knowledge_base_id,
                payload(),
                storage=FakeObjectStorage(),
                now=datetime(2026, 10, 27),
            )
        with pytest.raises(ValueError, match="positive"):
            create_pending_document(
                db,
                alice,
                workspace_id,
                knowledge_base_id,
                payload(),
                storage=FakeObjectStorage(),
                upload_ttl=timedelta(0),
            )


def test_missing_document_returns_safe_not_found(clients):
    alice_client, _, engine = clients
    workspace_id, knowledge_base_id = hierarchy(alice_client)
    with Session(engine) as db:
        alice, _ = users(db)
        with pytest.raises(AppError) as error:
            get_document(db, alice, workspace_id, knowledge_base_id, uuid4())
        assert error.value.code == "DOCUMENT_NOT_FOUND"
        assert error.value.message == "Document not found."


def test_complete_document_verifies_and_persists_storage_metadata(clients):
    alice_client, _, engine = clients
    workspace_id, knowledge_base_id = hierarchy(alice_client)
    completed_at = datetime(2026, 10, 27, 13, 0, tzinfo=UTC)
    with Session(engine) as db:
        alice, _ = users(db)
        storage = FakeObjectStorage(provider="gcs", bucket="documents-test")
        document = create_pending_document(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            payload(),
            storage=storage,
        ).document
        storage.objects[document.storage_object_key] = StoredObjectMetadata(
            size_bytes=1024,
            content_type="application/pdf",
            version="123",
            checksum="checksum",
            checksum_algorithm="crc32c",
        )

        completed_result = complete_document_upload(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            document.id,
            storage=storage,
            now=completed_at,
        )
        completed = completed_result.document
        job_id = completed_result.job.id
        first_uploaded_at = completed.uploaded_at
        retried_result = complete_document_upload(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            document.id,
            storage=storage,
            now=completed_at + timedelta(minutes=1),
        )
        retried = retried_result.document

        assert retried.upload_status == "STORED"
        assert retried.stored_size_bytes == 1024
        assert retried.storage_version == "123"
        assert retried.storage_checksum == "checksum"
        assert retried.storage_checksum_algorithm == "crc32c"
        assert retried.uploaded_at == first_uploaded_at
        assert retried.processing_status == "QUEUED"
        assert retried_result.job.id == job_id
        assert retried_result.job.status == "QUEUED"
        assert retried_result.job.attempt_count == 0
        assert retried_result.job.max_attempts == 3
        assert db.scalar(select(IngestionJob).where(IngestionJob.id == job_id))
        events = db.scalars(select(OutboxEvent)).all()
        assert len(events) == 1
        assert events[0].aggregate_id == job_id
        assert events[0].event_type == "INGESTION_JOB_REQUESTED"
        assert events[0].payload == {
            "job_id": str(job_id),
            "document_id": str(completed.id),
            "purpose": "INITIAL_INGESTION",
        }
        assert events[0].published_at is None

        retried_result.job.status = "PROCESSING"
        retried.processing_status = "PROCESSING"
        db.flush()
        completed_again = complete_document_upload(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            document.id,
            storage=storage,
            now=completed_at + timedelta(minutes=2),
        )
        assert completed_again.job.id == job_id
        assert completed_again.document.processing_status == "PROCESSING"
        assert len(db.scalars(select(OutboxEvent)).all()) == 1


def test_complete_document_rejects_missing_object(clients):
    alice_client, _, engine = clients
    workspace_id, knowledge_base_id = hierarchy(alice_client)
    with Session(engine) as db:
        alice, _ = users(db)
        storage = FakeObjectStorage()
        document = create_pending_document(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            payload(),
            storage=storage,
        ).document
        with pytest.raises(AppError) as error:
            complete_document_upload(
                db,
                alice,
                workspace_id,
                knowledge_base_id,
                document.id,
                storage=storage,
            )
        assert error.value.code == "DOCUMENT_UPLOAD_INCOMPLETE"
        assert document.upload_status == "PENDING"


@pytest.mark.parametrize(
    "size_bytes,content_type",
    [(1025, "application/pdf"), (1024, "text/plain")],
)
def test_complete_document_rejects_metadata_mismatch(clients, size_bytes, content_type):
    alice_client, _, engine = clients
    workspace_id, knowledge_base_id = hierarchy(alice_client)
    with Session(engine) as db:
        alice, _ = users(db)
        storage = FakeObjectStorage()
        document = create_pending_document(
            db,
            alice,
            workspace_id,
            knowledge_base_id,
            payload(),
            storage=storage,
        ).document
        storage.objects[document.storage_object_key] = StoredObjectMetadata(
            size_bytes=size_bytes,
            content_type=content_type,
        )
        with pytest.raises(AppError) as error:
            complete_document_upload(
                db,
                alice,
                workspace_id,
                knowledge_base_id,
                document.id,
                storage=storage,
            )
        assert error.value.code == "DOCUMENT_UPLOAD_MISMATCH"
        assert document.upload_status == "PENDING"
