"""Validate and load the immutable object used by an ingestion job."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from backend.documents.schemas import (
    ALLOWED_DECLARED_CONTENT_TYPES,
    MAX_DOCUMENT_SIZE_BYTES,
)
from backend.ingestion.claim import ClaimedIngestionJob, SessionFactory
from backend.models import Document, IngestionJob
from backend.object_storage import ObjectStorage, ObjectVersionMismatchError


class SourceValidationError(ValueError):
    """A permanent source problem that retrying cannot repair."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidatedSource:
    document_id: UUID
    original_filename: str
    content_type: str
    storage_version: str | None
    content: bytes


@dataclass(frozen=True)
class _SourceDescriptor:
    document_id: UUID
    original_filename: str
    declared_content_type: str
    declared_size_bytes: int
    stored_size_bytes: int | None
    storage_provider: str
    storage_bucket: str
    storage_object_key: str
    storage_version: str | None
    storage_checksum: str | None
    storage_checksum_algorithm: str | None
    source_storage_version: str | None
    upload_status: str


class SourceValidator:
    """Re-check stored metadata, then download and inspect source bytes."""

    def __init__(
        self,
        session_factory: SessionFactory,
        storage: ObjectStorage,
        *,
        max_size_bytes: int = MAX_DOCUMENT_SIZE_BYTES,
    ) -> None:
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be positive")
        self._session_factory = session_factory
        self._storage = storage
        self._max_size_bytes = max_size_bytes

    def validate(self, claimed: ClaimedIngestionJob) -> ValidatedSource:
        with self._session_factory() as db:
            source = self._load_descriptor(db, claimed)

        self._validate_location(source)
        try:
            metadata = self._storage.get_object_metadata(source.storage_object_key)
        except FileNotFoundError as exc:
            raise SourceValidationError(
                "SOURCE_OBJECT_NOT_FOUND",
                "The uploaded source object was not found.",
            ) from exc

        expected_version = source.source_storage_version or source.storage_version
        self._validate_metadata(source, metadata, expected_version)
        try:
            content = self._storage.read_object(
                source.storage_object_key,
                version=expected_version,
            )
        except FileNotFoundError as exc:
            raise SourceValidationError(
                "SOURCE_OBJECT_NOT_FOUND",
                "The uploaded source object was not found.",
            ) from exc
        except ObjectVersionMismatchError as exc:
            raise SourceValidationError(
                "SOURCE_VERSION_CHANGED",
                "The source object changed after this ingestion job was queued.",
            ) from exc

        if len(content) != metadata.size_bytes:
            raise SourceValidationError(
                "SOURCE_SIZE_MISMATCH",
                "Downloaded source size does not match its stored metadata.",
            )
        self._validate_content(content, source.declared_content_type)
        return ValidatedSource(
            document_id=source.document_id,
            original_filename=source.original_filename,
            content_type=source.declared_content_type,
            storage_version=metadata.version,
            content=content,
        )

    @staticmethod
    def _load_descriptor(
        db: Session,
        claimed: ClaimedIngestionJob,
    ) -> _SourceDescriptor:
        document = db.get(Document, claimed.document_id)
        job = db.get(IngestionJob, claimed.job_id)
        if document is None or job is None or job.document_id != claimed.document_id:
            raise SourceValidationError(
                "SOURCE_RECORD_NOT_FOUND",
                "The document source record no longer exists.",
            )
        return _SourceDescriptor(
            document_id=document.id,
            original_filename=document.original_filename,
            declared_content_type=document.declared_content_type,
            declared_size_bytes=document.declared_size_bytes,
            stored_size_bytes=document.stored_size_bytes,
            storage_provider=document.storage_provider,
            storage_bucket=document.storage_bucket,
            storage_object_key=document.storage_object_key,
            storage_version=document.storage_version,
            storage_checksum=document.storage_checksum,
            storage_checksum_algorithm=document.storage_checksum_algorithm,
            source_storage_version=job.source_storage_version,
            upload_status=document.upload_status,
        )

    def _validate_location(self, source: _SourceDescriptor) -> None:
        if source.upload_status != "STORED":
            raise SourceValidationError(
                "SOURCE_NOT_STORED",
                "The document upload is not in the stored state.",
            )
        if (
            source.storage_provider != self._storage.provider
            or source.storage_bucket != self._storage.bucket
        ):
            raise SourceValidationError(
                "SOURCE_STORAGE_MISMATCH",
                "The source location does not match the configured storage.",
            )
        if source.declared_content_type not in ALLOWED_DECLARED_CONTENT_TYPES:
            raise SourceValidationError(
                "SOURCE_TYPE_UNSUPPORTED",
                "The source content type is not supported.",
            )

    def _validate_metadata(self, source, metadata, expected_version) -> None:
        if metadata.size_bytes <= 0:
            raise SourceValidationError("SOURCE_EMPTY", "The source object is empty.")
        if metadata.size_bytes > self._max_size_bytes:
            raise SourceValidationError(
                "SOURCE_TOO_LARGE",
                "The source object exceeds the ingestion size limit.",
            )
        if (
            source.stored_size_bytes is None
            or metadata.size_bytes != source.declared_size_bytes
            or metadata.size_bytes != source.stored_size_bytes
        ):
            raise SourceValidationError(
                "SOURCE_SIZE_MISMATCH",
                "The source size no longer matches the document record.",
            )
        if metadata.content_type != source.declared_content_type:
            raise SourceValidationError(
                "SOURCE_TYPE_MISMATCH",
                "The source content type no longer matches the document record.",
            )
        if expected_version is not None and metadata.version != expected_version:
            raise SourceValidationError(
                "SOURCE_VERSION_CHANGED",
                "The source object changed after this ingestion job was queued.",
            )
        if (
            source.storage_checksum is not None
            and metadata.checksum != source.storage_checksum
        ):
            raise SourceValidationError(
                "SOURCE_CHECKSUM_MISMATCH",
                "The source checksum no longer matches the document record.",
            )
        if (
            source.storage_checksum_algorithm is not None
            and metadata.checksum_algorithm != source.storage_checksum_algorithm
        ):
            raise SourceValidationError(
                "SOURCE_CHECKSUM_MISMATCH",
                "The source checksum algorithm no longer matches the document record.",
            )

    @staticmethod
    def _validate_content(content: bytes, content_type: str) -> None:
        if not content:
            raise SourceValidationError("SOURCE_EMPTY", "The source object is empty.")
        if content_type == "application/pdf":
            if b"%PDF-" not in content[:1024]:
                raise SourceValidationError(
                    "SOURCE_SIGNATURE_INVALID",
                    "The source bytes do not contain a valid PDF header.",
                )
            return
        if b"\x00" in content:
            raise SourceValidationError(
                "SOURCE_TEXT_INVALID",
                "The text source contains binary null bytes.",
            )
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SourceValidationError(
                "SOURCE_TEXT_INVALID",
                "The text source is not valid UTF-8.",
            ) from exc
