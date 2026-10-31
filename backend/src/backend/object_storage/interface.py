"""Port implemented by each object-storage provider adapter."""

from datetime import datetime
from typing import Protocol

from backend.object_storage.schemas import StoredObjectMetadata, UploadInstructions


class ObjectStorage(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def bucket(self) -> str: ...

    def create_upload_grant(
        self,
        *,
        object_key: str,
        content_type: str,
        size_bytes: int,
        expires_at: datetime,
    ) -> UploadInstructions: ...

    def get_object_metadata(self, object_key: str) -> StoredObjectMetadata: ...

    def read_object(
        self,
        object_key: str,
        *,
        version: str | None = None,
    ) -> bytes: ...

    def delete_object(self, object_key: str) -> None: ...
