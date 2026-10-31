"""Deterministic in-memory storage adapter for unit and API tests."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from backend.object_storage.errors import ObjectVersionMismatchError
from backend.object_storage.schemas import StoredObjectMetadata, UploadInstructions


@dataclass(frozen=True)
class UploadGrantRequest:
    object_key: str
    content_type: str
    size_bytes: int
    expires_at: datetime


class FakeObjectStorage:
    def __init__(self, *, provider: str = "fake", bucket: str = "test-bucket"):
        if not provider.strip() or not bucket.strip():
            raise ValueError("provider and bucket must be nonempty")
        self._provider = provider
        self._bucket = bucket
        self.upload_requests: list[UploadGrantRequest] = []
        self.objects: dict[str, StoredObjectMetadata] = {}
        self.object_contents: dict[str, bytes] = {}

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def bucket(self) -> str:
        return self._bucket

    def create_upload_grant(
        self,
        *,
        object_key: str,
        content_type: str,
        size_bytes: int,
        expires_at: datetime,
    ) -> UploadInstructions:
        self.upload_requests.append(
            UploadGrantRequest(
                object_key=object_key,
                content_type=content_type,
                size_bytes=size_bytes,
                expires_at=expires_at,
            )
        )
        return UploadInstructions(
            url=(
                f"https://storage.invalid/{quote(self.provider, safe='')}/"
                f"{quote(self.bucket, safe='')}/{quote(object_key, safe='/')}"
            ),
            method="PUT",
            headers={
                "Content-Type": content_type,
                "X-Expected-Size": str(size_bytes),
            },
            expires_at=expires_at,
        )

    def get_object_metadata(self, object_key: str) -> StoredObjectMetadata:
        try:
            return self.objects[object_key]
        except KeyError as exc:
            raise FileNotFoundError(object_key) from exc

    def read_object(
        self,
        object_key: str,
        *,
        version: str | None = None,
    ) -> bytes:
        metadata = self.get_object_metadata(object_key)
        if version is not None and metadata.version != version:
            raise ObjectVersionMismatchError(object_key)
        try:
            return self.object_contents[object_key]
        except KeyError as exc:
            raise FileNotFoundError(object_key) from exc

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)
        self.object_contents.pop(object_key, None)

    def write_object(
        self,
        object_key: str,
        content: bytes,
        *,
        content_type: str,
    ) -> StoredObjectMetadata:
        if not object_key.strip() or not content or not content_type.strip():
            raise ValueError("object key, content, and content type must be nonempty")
        version = (
            str(int(self.objects.get(object_key).version or "0") + 1)
            if object_key in self.objects
            else "1"
        )
        metadata = StoredObjectMetadata(
            size_bytes=len(content),
            content_type=content_type,
            version=version,
            checksum=hashlib.sha256(content).hexdigest(),
            checksum_algorithm="sha256",
        )
        self.objects[object_key] = metadata
        self.object_contents[object_key] = content
        return metadata
