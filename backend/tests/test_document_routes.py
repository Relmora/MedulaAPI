from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_knowledge_base_routes import collection, workspace
from test_workspace_routes import clients as clients

from backend.main import app
from backend.models import Document, IngestionJob, OutboxEvent
from backend.object_storage.dependencies import get_object_storage
from backend.object_storage.fake import FakeObjectStorage
from backend.object_storage.schemas import StoredObjectMetadata


def document_collection(client):
    workspace_id = workspace(client)
    knowledge_base_id = client.post(
        collection(workspace_id), json={"name": "Documents"}
    ).json()["id"]
    return f"/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/documents"


def valid_payload():
    return {
        "original_filename": "notes.pdf",
        "declared_content_type": "application/pdf",
        "declared_size_bytes": 42,
    }


def test_upload_intent_creates_pending_row_and_returns_signed_instructions(clients):
    alice, _, engine = clients
    storage = FakeObjectStorage(provider="gcs", bucket="documents-test")
    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        response = alice.post(
            f"{document_collection(alice)}/upload-intent", json=valid_payload()
        )
    finally:
        app.dependency_overrides.pop(get_object_storage, None)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"document_id", "upload"}
    assert body["upload"]["method"] == "PUT"
    assert body["upload"]["headers"]["Content-Type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    with Session(engine) as db:
        document = db.scalar(select(Document))
        assert str(document.id) == body["document_id"]
        assert document.upload_status == "PENDING"
        assert document.storage_provider == "gcs"
        assert document.storage_bucket == "documents-test"


def test_upload_intent_enforces_ownership_authentication_and_origin(clients):
    alice, bob, _ = clients
    storage = FakeObjectStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        path = f"{document_collection(alice)}/upload-intent"
        assert bob.post(path, json=valid_payload()).status_code == 404
        assert (
            alice.post(
                path,
                json=valid_payload(),
                headers={"Origin": "https://attacker.example"},
            ).status_code
            == 403
        )
        alice.cookies.clear()
        assert alice.post(path, json=valid_payload()).status_code == 401
    finally:
        app.dependency_overrides.pop(get_object_storage, None)


def test_upload_intent_rejects_unsupported_or_oversized_files(clients):
    alice, _, _ = clients
    storage = FakeObjectStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        path = f"{document_collection(alice)}/upload-intent"
        unsupported = valid_payload() | {"declared_content_type": "image/png"}
        oversized = valid_payload() | {"declared_size_bytes": 25 * 1024 * 1024 + 1}
        assert alice.post(path, json=unsupported).status_code == 422
        assert alice.post(path, json=oversized).status_code == 422
    finally:
        app.dependency_overrides.pop(get_object_storage, None)


def test_complete_upload_verifies_object_and_is_idempotent(clients):
    alice, _, engine = clients
    storage = FakeObjectStorage(provider="gcs", bucket="documents-test")
    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        path = document_collection(alice)
        intent = alice.post(f"{path}/upload-intent", json=valid_payload()).json()
        with Session(engine) as db:
            document = db.get(Document, UUID(intent["document_id"]))
            object_key = document.storage_object_key
        storage.objects[object_key] = StoredObjectMetadata(
            size_bytes=42,
            content_type="application/pdf",
            version="generation-1",
            checksum="checksum",
            checksum_algorithm="crc32c",
        )

        target = f"{path}/{intent['document_id']}/complete"
        response = alice.post(target, json={})
        retried = alice.post(target, json={})
    finally:
        app.dependency_overrides.pop(get_object_storage, None)

    assert response.status_code == 200
    assert retried.status_code == 200
    assert response.json() == retried.json()
    assert response.json()["upload_status"] == "STORED"
    assert response.json()["processing_status"] == "QUEUED"
    assert response.json()["stored_size_bytes"] == 42
    assert response.headers["cache-control"] == "no-store"
    with Session(engine) as db:
        document = db.get(Document, UUID(intent["document_id"]))
        assert document.upload_status == "STORED"
        assert document.storage_version == "generation-1"
        assert document.processing_status == "QUEUED"
        job = db.scalar(select(IngestionJob))
        assert job is not None
        assert str(job.id) == response.json()["job_id"]
        assert job.document_id == document.id
        assert job.purpose == "INITIAL_INGESTION"
        assert job.pipeline_version == "v1"
        assert job.source_storage_version == "generation-1"
        assert job.status == "QUEUED"
        assert job.attempt_count == 0
        assert job.max_attempts == 3
        assert db.scalars(select(IngestionJob)).all() == [job]
        event = db.scalar(select(OutboxEvent))
        assert event is not None
        assert event.aggregate_type == "INGESTION_JOB"
        assert event.aggregate_id == job.id
        assert event.payload == {
            "job_id": str(job.id),
            "document_id": str(document.id),
            "purpose": "INITIAL_INGESTION",
        }
        assert event.published_at is None
        assert db.scalars(select(OutboxEvent)).all() == [event]


def test_complete_upload_enforces_ownership_and_origin(clients):
    alice, bob, engine = clients
    storage = FakeObjectStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        path = document_collection(alice)
        intent = alice.post(f"{path}/upload-intent", json=valid_payload()).json()
        with Session(engine) as db:
            document = db.get(Document, UUID(intent["document_id"]))
            object_key = document.storage_object_key
        storage.objects[object_key] = StoredObjectMetadata(
            size_bytes=42,
            content_type="application/pdf",
        )
        target = f"{path}/{intent['document_id']}/complete"
        assert bob.post(target, json={}).status_code == 404
        assert (
            alice.post(
                target,
                json={},
                headers={"Origin": "https://attacker.example"},
            ).status_code
            == 403
        )
    finally:
        app.dependency_overrides.pop(get_object_storage, None)
