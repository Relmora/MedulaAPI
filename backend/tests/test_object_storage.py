from datetime import UTC, datetime, timedelta

import pytest

from backend.object_storage.factory import ObjectStorageFactory
from backend.object_storage.fake import FakeObjectStorage
from backend.object_storage.schemas import StoredObjectMetadata


def test_factory_selects_registered_provider():
    storage = FakeObjectStorage(provider="gcs", bucket="documents")
    factory = ObjectStorageFactory([storage])
    assert factory.create("gcs") is storage
    with pytest.raises(ValueError, match="unsupported"):
        factory.create("s3")
    with pytest.raises(ValueError, match="already registered"):
        factory.register(FakeObjectStorage(provider="gcs", bucket="other"))


def test_fake_storage_generates_provider_neutral_upload_instructions():
    storage = FakeObjectStorage(provider="test", bucket="documents")
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    upload = storage.create_upload_grant(
        object_key="documents/id/original",
        content_type="application/pdf",
        size_bytes=42,
        expires_at=expires_at,
    )
    assert upload.method == "PUT"
    assert upload.form_fields is None
    assert upload.headers["Content-Type"] == "application/pdf"
    assert upload.expires_at == expires_at
    assert storage.upload_requests[0].size_bytes == 42


def test_fake_storage_metadata_and_idempotent_delete():
    storage = FakeObjectStorage()
    metadata = StoredObjectMetadata(
        size_bytes=42,
        content_type="application/pdf",
        version="version-1",
        checksum="checksum",
        checksum_algorithm="crc32c",
    )
    storage.objects["documents/id/original"] = metadata
    assert storage.get_object_metadata("documents/id/original") == metadata
    storage.delete_object("documents/id/original")
    storage.delete_object("documents/id/original")
    with pytest.raises(FileNotFoundError):
        storage.get_object_metadata("documents/id/original")


@pytest.mark.parametrize("provider,bucket", [("", "bucket"), ("gcs", "")])
def test_fake_storage_rejects_invalid_location(provider, bucket):
    with pytest.raises(ValueError, match="nonempty"):
        FakeObjectStorage(provider=provider, bucket=bucket)
