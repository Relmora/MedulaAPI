"""Deterministic parser for validated UTF-8 plain-text documents."""

import re

from backend.ingestion.parsing.interface import ParseError
from backend.ingestion.parsing.models import (
    ParsedBlock,
    ParsedDocument,
    ParseStatistics,
)
from backend.ingestion.stages import ValidatedSource

PARAGRAPH_SEPARATOR = re.compile(r"(?:\r?\n)[\t ]*(?:\r?\n)+")


class PlainTextParser:
    @property
    def name(self) -> str:
        return "plain_text"

    @property
    def version(self) -> str:
        return "1"

    @property
    def content_types(self) -> frozenset[str]:
        return frozenset({"text/plain"})

    def parse(self, source: ValidatedSource) -> ParsedDocument:
        if source.content_type not in self.content_types:
            raise ParseError(
                "PARSE_UNSUPPORTED_TYPE",
                f"PlainTextParser does not support {source.content_type}.",
            )
        try:
            decoded = source.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ParseError(
                "PARSE_TEXT_ENCODING_INVALID",
                "Plain-text source is not valid UTF-8.",
            ) from exc

        paragraphs = [
            paragraph.strip()
            for paragraph in PARAGRAPH_SEPARATOR.split(decoded)
            if paragraph.strip()
        ]
        if not paragraphs:
            raise ParseError(
                "PARSE_NO_TEXT",
                "Plain-text source contains no useful text.",
            )

        blocks = tuple(
            ParsedBlock(
                block_index=index,
                block_type="paragraph",
                text=paragraph,
            )
            for index, paragraph in enumerate(paragraphs)
        )
        return ParsedDocument(
            document_id=source.document_id,
            source_storage_version=source.storage_version,
            parser_name=self.name,
            parser_version=self.version,
            content_type=source.content_type,
            blocks=blocks,
            statistics=ParseStatistics(
                block_count=len(blocks),
                extracted_character_count=sum(len(block.text) for block in blocks),
            ),
        )
