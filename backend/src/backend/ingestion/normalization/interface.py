"""Common normalization contract used by the NORMALIZE stage."""

from typing import Protocol

from backend.ingestion.normalization.models import NormalizedDocument
from backend.ingestion.parsing.models import ParsedDocument


class NormalizationError(ValueError):
    """A classified, permanent failure to normalize a parsed document."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("normalization error code must be nonempty")
        super().__init__(message)
        self.code = normalized_code


class Normalizer(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def normalize(self, document: ParsedDocument) -> NormalizedDocument: ...
