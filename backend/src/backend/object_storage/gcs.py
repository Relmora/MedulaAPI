"""Google Cloud Storage implementation of the object-storage port."""

from datetime import datetime

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

from backend.object_storage.errors import ObjectVersionMismatchError
from backend.object_storage.schemas import StoredObjectMetadata, UploadInstructions


class GCSObjectStorage:
    """Store private document objects in one configured GCS bucket."""

    def __init__(
        self,
        *,
        bucket: str,
        project_id: str | None = None,
        client: storage.Client | None = None,
    ):
        if not bucket.strip():
            raise ValueError("storage bucket must be nonempty")
        self._bucket = bucket
        self._client = client or storage.Client(project=project_id)

    @property
    def provider(self) -> str:
        return "gcs"

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
        if not object_key.strip():
            raise ValueError("object key must be nonempty")
        if not content_type.strip():
            raise ValueError("content type must be nonempty")
        if size_bytes <= 0:
            raise ValueError("size_bytes must be positive")
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")

        size_range = f"{size_bytes},{size_bytes}"
        blob = self._client.bucket(self.bucket).blob(object_key)
        url = blob.generate_signed_url(
            version="v4",
            expiration=expires_at,
            method="PUT",
            content_type=content_type,
            headers={"x-goog-content-length-range": size_range},
        )
        return UploadInstructions(
            url=url,
            method="PUT",
            headers={
                "Content-Type": content_type,
                "x-goog-content-length-range": size_range,
            },
            expires_at=expires_at,
        )

    def get_object_metadata(self, object_key: str) -> StoredObjectMetadata:
        blob = self._client.bucket(self.bucket).blob(object_key)
        try:
            blob.reload()
        except NotFound as exc:
            raise FileNotFoundError(object_key) from exc

        checksum = blob.crc32c
        checksum_algorithm = "crc32c" if checksum is not None else None
        if checksum is None and blob.md5_hash is not None:
            checksum = blob.md5_hash
            checksum_algorithm = "md5"

        return StoredObjectMetadata(
            size_bytes=blob.size or 0,
            content_type=blob.content_type,
            version=str(blob.generation) if blob.generation is not None else None,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
        )

    def read_object(
        self,
        object_key: str,
        *,
        version: str | None = None,
    ) -> bytes:
        blob = self._client.bucket(self.bucket).blob(object_key)
        generation = None
        if version is not None:
            try:
                generation = int(version)
            except ValueError as exc:
                raise ObjectVersionMismatchError(
                    f"invalid GCS generation: {version}"
                ) from exc
        try:
            return blob.download_as_bytes(if_generation_match=generation)
        except NotFound as exc:
            raise FileNotFoundError(object_key) from exc
        except PreconditionFailed as exc:
            raise ObjectVersionMismatchError(object_key) from exc

    def delete_object(self, object_key: str) -> None:
        blob = self._client.bucket(self.bucket).blob(object_key)
        try:
            blob.delete()
        except NotFound:
            return

    def write_object(
        self,
        object_key: str,
        content: bytes,
        *,
        content_type: str,
    ) -> StoredObjectMetadata:
        if not object_key.strip() or not content or not content_type.strip():
            raise ValueError("object key, content, and content type must be nonempty")
        blob = self._client.bucket(self.bucket).blob(object_key)
        blob.upload_from_string(content, content_type=content_type)
        blob.reload()
        checksum = blob.crc32c
        checksum_algorithm = "crc32c" if checksum is not None else None
        if checksum is None and blob.md5_hash is not None:
            checksum = blob.md5_hash
            checksum_algorithm = "md5"
        return StoredObjectMetadata(
            size_bytes=blob.size or len(content),
            content_type=blob.content_type or content_type,
            version=str(blob.generation) if blob.generation is not None else None,
            checksum=checksum,
            checksum_algorithm=checksum_algorithm,
        )
