from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from backend.object_storage import ObjectVersionMismatchError
from backend.object_storage.gcs import GCSObjectStorage


def make_storage():
    blob = Mock()
    bucket = Mock()
    bucket.blob.return_value = blob
    client = Mock()
    client.bucket.return_value = bucket
    return GCSObjectStorage(bucket="documents", client=client), client, bucket, blob


def test_gcs_upload_grant_signs_type_size_and_expiry():
    storage, client, bucket, blob = make_storage()
    blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed"
    expires_at = datetime.now(UTC) + timedelta(minutes=15)

    upload = storage.create_upload_grant(
        object_key="documents/id/original",
        content_type="application/pdf",
        size_bytes=42,
        expires_at=expires_at,
    )

    client.bucket.assert_called_once_with("documents")
    bucket.blob.assert_called_once_with("documents/id/original")
    blob.generate_signed_url.assert_called_once_with(
        version="v4",
        expiration=expires_at,
        method="PUT",
        content_type="application/pdf",
        headers={"x-goog-content-length-range": "42,42"},
    )
    assert upload.url == "https://storage.googleapis.com/signed"
    assert upload.headers == {
        "Content-Type": "application/pdf",
        "x-goog-content-length-range": "42,42",
    }


def test_gcs_reads_provider_neutral_metadata():
    storage, _, _, blob = make_storage()
    blob.size = 42
    blob.content_type = "application/pdf"
    blob.generation = 123
    blob.crc32c = "crc-value"
    blob.md5_hash = "md5-value"

    metadata = storage.get_object_metadata("documents/id/original")

    assert metadata.size_bytes == 42
    assert metadata.content_type == "application/pdf"
    assert metadata.version == "123"
    assert metadata.checksum == "crc-value"
    assert metadata.checksum_algorithm == "crc32c"


def test_gcs_reads_the_requested_immutable_generation():
    storage, _, _, blob = make_storage()
    blob.download_as_bytes.return_value = b"document"

    content = storage.read_object("documents/id/original", version="123")

    assert content == b"document"
    blob.download_as_bytes.assert_called_once_with(if_generation_match=123)


def test_gcs_maps_changed_generation_to_provider_neutral_error():
    storage, _, _, blob = make_storage()
    blob.download_as_bytes.side_effect = PreconditionFailed("changed")

    with pytest.raises(ObjectVersionMismatchError):
        storage.read_object("documents/id/original", version="123")


def test_gcs_maps_missing_object_and_delete_is_idempotent():
    storage, _, _, blob = make_storage()
    blob.reload.side_effect = NotFound("missing")
    with pytest.raises(FileNotFoundError):
        storage.get_object_metadata("missing")

    blob.delete.side_effect = NotFound("missing")
    storage.delete_object("missing")


@pytest.mark.parametrize(
    "object_key,content_type,size_bytes",
    [("", "application/pdf", 1), ("key", "", 1), ("key", "text/plain", 0)],
)
def test_gcs_rejects_invalid_upload_grant_inputs(object_key, content_type, size_bytes):
    storage, _, _, _ = make_storage()
    with pytest.raises(ValueError):
        storage.create_upload_grant(
            object_key=object_key,
            content_type=content_type,
            size_bytes=size_bytes,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
