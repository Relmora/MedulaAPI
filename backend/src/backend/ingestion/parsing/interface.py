"""Common parser interface used by the PARSE stage."""

from typing import Protocol

from backend.ingestion.parsing.models import ParsedDocument
from backend.ingestion.stages import ValidatedSource


class ParseError(ValueError):
    """A classified, permanent failure to parse validated source bytes."""

    def __init__(self, code: str, message: str) -> None:
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("parse error code must be nonempty")
        super().__init__(message)
        self.code = normalized_code


class DocumentParser(Protocol):
    """Convert one supported source format to a common parsed document."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def content_types(self) -> frozenset[str]: ...

    def parse(self, source: ValidatedSource) -> ParsedDocument: ...
