from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_knowledge_base_routes import collection, workspace
from test_workspace_routes import clients as clients

from backend.main import app
from backend.models import (
    Document,
    Entity,
    EntityRelationship,
    IngestionJob,
    OutboxEvent,
)
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


def create_document_intent(client, path):
    storage = FakeObjectStorage(provider="gcs", bucket="documents-test")
    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        response = client.post(f"{path}/upload-intent", json=valid_payload())
    finally:
        app.dependency_overrides.pop(get_object_storage, None)
    assert response.status_code == 201
    return response.json()


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
        assert document is not None
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
            assert document is not None
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
        assert document is not None
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
            assert document is not None
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


def test_document_graph_returns_deduplicated_nodes_and_edges(clients):
    alice, _, engine = clients
    path = document_collection(alice)
    intent = create_document_intent(alice, path)
    document_id = UUID(intent["document_id"])
    with Session(engine) as db:
        document = db.get(Document, document_id)
        assert document is not None
        document.processing_status = "READY"
        sanjay = Entity(
            knowledge_base_id=document.knowledge_base_id,
            name="Sanjay",
            normalized_name="sanjay",
            entity_type="PERSON",
        )
        medula = Entity(
            knowledge_base_id=document.knowledge_base_id,
            name="Medula",
            normalized_name="medula",
            entity_type="ORGANIZATION",
        )
        bengaluru = Entity(
            knowledge_base_id=document.knowledge_base_id,
            name="Bengaluru",
            normalized_name="bengaluru",
            entity_type="LOCATION",
        )
        db.add_all((sanjay, medula, bengaluru))
        db.flush()
        works_at = EntityRelationship(
            knowledge_base_id=document.knowledge_base_id,
            subject_entity_id=sanjay.id,
            predicate="WORKS_AT",
            object_entity_id=medula.id,
            document_id=document.id,
            chunk_id=uuid4(),
        )
        located_in = EntityRelationship(
            knowledge_base_id=document.knowledge_base_id,
            subject_entity_id=medula.id,
            predicate="LOCATED_IN",
            object_entity_id=bengaluru.id,
            document_id=document.id,
            chunk_id=uuid4(),
        )
        db.add_all((works_at, located_in))
        db.commit()
        expected_node_ids = {str(sanjay.id), str(medula.id), str(bengaluru.id)}
        expected_edges = {
            (str(sanjay.id), "WORKS_AT", str(medula.id)),
            (str(medula.id), "LOCATED_IN", str(bengaluru.id)),
        }

    response = alice.get(f"{path}/{document_id}/graph")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    graph = response.json()
    assert graph["document_id"] == str(document_id)
    assert {node["id"] for node in graph["nodes"]} == expected_node_ids
    assert len(graph["nodes"]) == 3
    assert {
        (edge["source"], edge["predicate"], edge["target"]) for edge in graph["edges"]
    } == expected_edges
    assert all("chunk_id" in edge for edge in graph["edges"])


def test_knowledge_base_graph_aggregates_relationships_across_documents(clients):
    alice, bob, engine = clients
    documents_path = document_collection(alice)
    first_id = UUID(create_document_intent(alice, documents_path)["document_id"])
    second_id = UUID(create_document_intent(alice, documents_path)["document_id"])
    knowledge_base_path = documents_path.removesuffix("/documents")

    with Session(engine) as db:
        first = db.get(Document, first_id)
        assert first is not None
        sanjay = Entity(
            knowledge_base_id=first.knowledge_base_id,
            name="Sanjay",
            normalized_name="sanjay",
            entity_type="PERSON",
        )
        medula = Entity(
            knowledge_base_id=first.knowledge_base_id,
            name="Medula",
            normalized_name="medula",
            entity_type="ORGANIZATION",
        )
        bengaluru = Entity(
            knowledge_base_id=first.knowledge_base_id,
            name="Bengaluru",
            normalized_name="bengaluru",
            entity_type="LOCATION",
        )
        db.add_all((sanjay, medula, bengaluru))
        db.flush()
        db.add_all(
            (
                EntityRelationship(
                    knowledge_base_id=first.knowledge_base_id,
                    subject_entity_id=sanjay.id,
                    predicate="WORKS_AT",
                    object_entity_id=medula.id,
                    document_id=first_id,
                    chunk_id=uuid4(),
                ),
                EntityRelationship(
                    knowledge_base_id=first.knowledge_base_id,
                    subject_entity_id=medula.id,
                    predicate="LOCATED_IN",
                    object_entity_id=bengaluru.id,
                    document_id=second_id,
                    chunk_id=uuid4(),
                ),
            )
        )
        db.commit()

    response = alice.get(f"{knowledge_base_path}/graph")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    graph = response.json()
    assert graph["knowledge_base_id"] == knowledge_base_path.rsplit("/", 1)[-1]
    assert {node["name"] for node in graph["nodes"]} == {
        "Sanjay",
        "Medula",
        "Bengaluru",
    }
    assert {
        edge["predicate"] for edge in graph["edges"]
    } == {"WORKS_AT", "LOCATED_IN"}
    assert bob.get(f"{knowledge_base_path}/graph").status_code == 404


def test_document_graph_handles_empty_not_ready_and_private_documents(clients):
    alice, bob, engine = clients
    path = document_collection(alice)
    first = create_document_intent(alice, path)
    second = create_document_intent(alice, path)
    ready_id = UUID(first["document_id"])
    pending_id = UUID(second["document_id"])
    with Session(engine) as db:
        document = db.get(Document, ready_id)
        assert document is not None
        document.processing_status = "READY"
        db.commit()

    response = alice.get(f"{path}/{ready_id}/graph")
    assert response.status_code == 200
    assert response.json() == {
        "document_id": str(ready_id),
        "nodes": [],
        "edges": [],
    }

    response = alice.get(f"{path}/{pending_id}/graph")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_GRAPH_NOT_READY"

    response = bob.get(f"{path}/{ready_id}/graph")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"

    alice.cookies.clear()
    assert alice.get(f"{path}/{ready_id}/graph").status_code == 401
