"""Common contract used by the CHUNK stage."""

from typing import Protocol

from backend.ingestion.chunking.models import ChunkedDocument
from backend.ingestion.normalization.models import NormalizedDocument


class ChunkingError(ValueError):
    """A classified, permanent failure to chunk a normalized document."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("chunking error code must be nonempty")
        super().__init__(message)
        self.code = normalized_code


class Chunker(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def chunk(
        self,
        document: NormalizedDocument,
        *,
        source_object_key: str,
        source_storage_version: str | None,
    ) -> ChunkedDocument: ...
