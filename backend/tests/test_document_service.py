from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_workspace_routes import clients as clients

from backend.documents.schemas import DocumentUploadIntentCreate
from backend.documents.service import create_pending_document, get_document
from backend.errors import AppError
from backend.models import Document, User
from backend.object_storage.fake import FakeObjectStorage


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
