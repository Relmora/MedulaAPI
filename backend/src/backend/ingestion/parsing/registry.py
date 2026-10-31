"""Content-type routing for document parsers."""

from collections.abc import Iterable

from backend.ingestion.parsing.interface import DocumentParser, ParseError


class ParserRegistry:
    def __init__(self, parsers: Iterable[DocumentParser] = ()) -> None:
        self._parsers: dict[str, DocumentParser] = {}
        for parser in parsers:
            self.register(parser)

    def register(self, parser: DocumentParser) -> None:
        if not parser.name.strip() or not parser.version.strip():
            raise ValueError("parser name and version must be nonempty")
        if not parser.content_types:
            raise ValueError("parser must support at least one content type")
        normalized_content_types = {
            content_type.strip().lower() for content_type in parser.content_types
        }
        if "" in normalized_content_types:
            raise ValueError("parser content types must be nonempty")
        duplicates = normalized_content_types & self._parsers.keys()
        if duplicates:
            duplicate = min(duplicates)
            raise ValueError(f"parser already registered for {duplicate}")
        for normalized_content_type in normalized_content_types:
            self._parsers[normalized_content_type] = parser

    def resolve(self, content_type: str) -> DocumentParser:
        normalized_content_type = content_type.strip().lower()
        try:
            return self._parsers[normalized_content_type]
        except KeyError as exc:
            raise ParseError(
                "PARSE_UNSUPPORTED_TYPE",
                f"No parser is registered for {normalized_content_type or 'empty'}.",
            ) from exc
