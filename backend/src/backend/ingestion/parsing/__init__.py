"""Provider-neutral document parsing contracts and implementations."""

from backend.ingestion.parsing.interface import DocumentParser, ParseError
from backend.ingestion.parsing.models import (
    BoundingBox,
    ParsedBlock,
    ParsedDocument,
    ParseStatistics,
)
from backend.ingestion.parsing.plain_text import PlainTextParser
from backend.ingestion.parsing.registry import ParserRegistry

__all__ = [
    "BoundingBox",
    "DocumentParser",
    "ParseError",
    "ParsedBlock",
    "ParsedDocument",
    "ParseStatistics",
    "ParserRegistry",
    "PlainTextParser",
]
