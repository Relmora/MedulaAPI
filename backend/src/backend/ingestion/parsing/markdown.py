"""Structure-preserving parser for CommonMark documents."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt
from markdown_it.token import Token

from backend.ingestion.parsing.interface import ParseError
from backend.ingestion.parsing.models import (
    ParsedBlock,
    ParsedDocument,
    ParseStatistics,
)

if TYPE_CHECKING:
    from backend.ingestion.stages.validate_source import ValidatedSource


class MarkdownParser:
    def __init__(self, markdown: MarkdownIt | None = None) -> None:
        self._markdown = markdown or MarkdownIt("commonmark").enable("table")

    @property
    def name(self) -> str:
        return "markdown"

    @property
    def version(self) -> str:
        return "1"

    @property
    def content_types(self) -> frozenset[str]:
        return frozenset({"text/markdown"})

    def parse(self, source: ValidatedSource) -> ParsedDocument:
        if source.content_type not in self.content_types:
            raise ParseError(
                "PARSE_UNSUPPORTED_TYPE",
                f"MarkdownParser does not support {source.content_type}.",
            )
        try:
            decoded = source.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ParseError(
                "PARSE_TEXT_ENCODING_INVALID",
                "Markdown source is not valid UTF-8.",
            ) from exc

        tokens = self._markdown.parse(decoded)
        blocks = self._extract_blocks(tokens)
        if not blocks:
            raise ParseError(
                "PARSE_NO_TEXT",
                "Markdown source contains no useful text.",
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

    def _extract_blocks(self, tokens: list[Token]) -> tuple[ParsedBlock, ...]:
        blocks: list[ParsedBlock] = []
        section_levels: list[str] = []
        list_depth = 0
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.type == "list_item_open":
                list_depth += 1
            elif token.type == "list_item_close":
                list_depth -= 1
            elif token.type == "heading_open" and index + 1 < len(tokens):
                inline = tokens[index + 1]
                level = int(token.tag.removeprefix("h"))
                text = self._inline_text(inline.children).strip()
                if text:
                    section_levels = section_levels[: level - 1]
                    section_levels.extend([""] * (level - 1 - len(section_levels)))
                    section_levels.append(text)
                    blocks.append(
                        ParsedBlock(
                            block_index=len(blocks),
                            block_type="heading",
                            text=text,
                            section_path=tuple(
                                section for section in section_levels if section
                            ),
                            metadata={"level": level},
                        )
                    )
                index += 1
            elif token.type == "paragraph_open" and index + 1 < len(tokens):
                inline = tokens[index + 1]
                text = self._inline_text(inline.children).strip()
                if text:
                    blocks.append(
                        ParsedBlock(
                            block_index=len(blocks),
                            block_type=("list_item" if list_depth else "paragraph"),
                            text=text,
                            section_path=tuple(
                                section for section in section_levels if section
                            ),
                            metadata=({"list_depth": list_depth} if list_depth else {}),
                        )
                    )
                index += 1
            elif token.type in {"fence", "code_block"}:
                text = token.content.rstrip("\n")
                if text:
                    metadata = {}
                    language = token.info.strip()
                    if language:
                        metadata["language"] = language
                    blocks.append(
                        ParsedBlock(
                            block_index=len(blocks),
                            block_type="code",
                            text=text,
                            section_path=tuple(
                                section for section in section_levels if section
                            ),
                            metadata=metadata,
                        )
                    )
            elif token.type == "table_open":
                table_tokens, closing_index = self._table_tokens(tokens, index)
                text = self._table_text(table_tokens)
                if text:
                    blocks.append(
                        ParsedBlock(
                            block_index=len(blocks),
                            block_type="table",
                            text=text,
                            section_path=tuple(
                                section for section in section_levels if section
                            ),
                        )
                    )
                index = closing_index
            index += 1
        return tuple(blocks)

    @staticmethod
    def _inline_text(children: Iterable[Token] | None) -> str:
        if children is None:
            return ""
        parts: list[str] = []
        for child in children:
            if child.type in {"text", "code_inline", "html_inline"}:
                parts.append(child.content)
            elif child.type in {"softbreak", "hardbreak"}:
                parts.append("\n")
            elif child.type == "image":
                parts.append(child.content)
        return "".join(parts)

    @staticmethod
    def _table_tokens(
        tokens: list[Token], opening_index: int
    ) -> tuple[list[Token], int]:
        depth = 0
        for index in range(opening_index, len(tokens)):
            token = tokens[index]
            if token.type == "table_open":
                depth += 1
            elif token.type == "table_close":
                depth -= 1
                if depth == 0:
                    return tokens[opening_index : index + 1], index
        return tokens[opening_index:], len(tokens) - 1

    def _table_text(self, tokens: list[Token]) -> str:
        rows: list[list[str]] = []
        row: list[str] | None = None
        for token in tokens:
            if token.type == "tr_open":
                row = []
            elif token.type == "tr_close" and row is not None:
                rows.append(row)
                row = None
            elif token.type == "inline" and row is not None:
                row.append(self._inline_text(token.children).strip())
        return "\n".join(
            "| " + " | ".join(cell.replace("\n", " ") for cell in row) + " |"
            for row in rows
        )
