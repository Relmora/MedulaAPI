"""Deterministic in-memory storage adapter for unit and API tests."""

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

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

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)
