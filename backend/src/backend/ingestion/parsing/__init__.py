"""Provider-neutral document parsing contracts and implementations."""

from backend.ingestion.parsing.interface import DocumentParser, ParseError
from backend.ingestion.parsing.markdown import MarkdownParser
from backend.ingestion.parsing.models import (
    BoundingBox,
    ParsedBlock,
    ParsedDocument,
    ParseStatistics,
)
from backend.ingestion.parsing.pdf import PdfParser
from backend.ingestion.parsing.plain_text import PlainTextParser
from backend.ingestion.parsing.registry import ParserRegistry

__all__ = [
    "BoundingBox",
    "DocumentParser",
    "MarkdownParser",
    "ParseError",
    "ParsedBlock",
    "ParsedDocument",
    "ParseStatistics",
    "ParserRegistry",
    "PdfParser",
    "PlainTextParser",
]
