"""Conservative deterministic normalization for parsed document blocks."""

import re
import unicodedata

from backend.ingestion.normalization.interface import NormalizationError
from backend.ingestion.normalization.models import (
    NormalizationStatistics,
    NormalizedBlock,
    NormalizedDocument,
)
from backend.ingestion.parsing.models import ParsedBlock, ParsedDocument

HORIZONTAL_WHITESPACE = re.compile(r"[^\S\n]+")
WHITESPACE_SENSITIVE_BLOCK_TYPES = frozenset({"code", "table"})


class DeterministicNormalizer:
    @property
    def name(self) -> str:
        return "deterministic"

    @property
    def version(self) -> str:
        return "1"

    def normalize(self, document: ParsedDocument) -> NormalizedDocument:
        blocks: list[NormalizedBlock] = []
        for source_block in document.blocks:
            text = self._normalize_text(source_block)
            if not text.strip():
                continue
            blocks.append(
                NormalizedBlock(
                    block_index=len(blocks),
                    source_block_index=source_block.block_index,
                    block_type=source_block.block_type,
                    text=text,
                    page_number=source_block.page_number,
                    section_path=source_block.section_path,
                    bounding_box=source_block.bounding_box,
                    metadata=source_block.metadata,
                )
            )

        if not blocks:
            raise NormalizationError(
                "NORMALIZE_NO_TEXT",
                "Normalization removed all useful document text.",
            )

        return NormalizedDocument(
            document_id=document.document_id,
            source_storage_version=document.source_storage_version,
            parsed_schema_version=document.schema_version,
            normalizer_name=self.name,
            normalizer_version=self.version,
            blocks=tuple(blocks),
            warnings=document.warnings,
            statistics=NormalizationStatistics(
                source_block_count=len(document.blocks),
                block_count=len(blocks),
                removed_block_count=len(document.blocks) - len(blocks),
                normalized_character_count=sum(len(block.text) for block in blocks),
            ),
        )

    @classmethod
    def _normalize_text(cls, block: ParsedBlock) -> str:
        text = block.text.replace("\r\n", "\n").replace("\r", "\n")
        text = unicodedata.normalize("NFC", text.replace("\u00a0", " "))
        text = "".join(
            character
            for character in text
            if character in {"\n", "\t"} or unicodedata.category(character) != "Cc"
        )
        if block.block_type in WHITESPACE_SENSITIVE_BLOCK_TYPES:
            return text.strip("\n")
        normalized_lines = (
            HORIZONTAL_WHITESPACE.sub(" ", line).strip() for line in text.split("\n")
        )
        return "\n".join(normalized_lines).strip()
