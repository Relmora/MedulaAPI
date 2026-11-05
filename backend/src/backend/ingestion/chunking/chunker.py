"""Deterministic, structure-aware character chunking."""

import hashlib
import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from backend.ingestion.chunking.interface import ChunkingError
from backend.ingestion.chunking.models import (
    ChunkedDocument,
    ChunkingConfig,
    ChunkingStatistics,
    ChunkSourceSpan,
    DocumentChunk,
)
from backend.ingestion.normalization.models import NormalizedBlock, NormalizedDocument

BREAK_AFTER_SENTENCE = re.compile(r"(?<=[.!?])\s+")
ATOMIC_BLOCK_TYPES = frozenset({"code", "table"})


@dataclass(frozen=True)
class _Piece:
    block: NormalizedBlock
    start: int
    end: int

    @property
    def text(self) -> str:
        return self.block.text[self.start : self.end]


class BlockAwareChunker:
    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    @property
    def name(self) -> str:
        return "block-aware"

    @property
    def version(self) -> str:
        return "1"

    def chunk(
        self,
        document: NormalizedDocument,
        *,
        source_object_key: str,
        source_storage_version: str | None,
    ) -> ChunkedDocument:
        if not source_object_key.strip():
            raise ChunkingError(
                "CHUNK_PROVENANCE_INVALID",
                "The normalized artifact object key is missing.",
            )
        if not document.blocks or not any(
            block.text.strip() for block in document.blocks
        ):
            raise ChunkingError("CHUNK_NO_TEXT", "No normalized text is available.")

        configuration_hash = hashlib.sha256(
            self.config.model_dump_json().encode("utf-8")
        ).hexdigest()
        drafts = self._build_drafts(document)
        chunks = tuple(
            self._create_chunk(
                document,
                pieces,
                chunk_index=index,
                configuration_hash=configuration_hash,
                source_storage_version=source_storage_version,
            )
            for index, pieces in enumerate(drafts)
        )
        sizes = [chunk.character_count for chunk in chunks]
        return ChunkedDocument(
            document_id=document.document_id,
            source_normalized_object_key=source_object_key,
            source_normalized_storage_version=source_storage_version,
            normalized_schema_version=document.schema_version,
            chunker_name=self.name,
            chunker_version=self.version,
            configuration=self.config,
            configuration_hash=configuration_hash,
            chunks=chunks,
            warnings=document.warnings,
            statistics=ChunkingStatistics(
                source_block_count=len(document.blocks),
                chunk_count=len(chunks),
                minimum_chunk_characters=min(sizes),
                maximum_chunk_characters=max(sizes),
                average_chunk_characters=sum(sizes) / len(sizes),
            ),
        )

    def _build_drafts(self, document: NormalizedDocument) -> list[list[_Piece]]:
        payload_limit = (
            self.config.max_chunk_characters - self.config.overlap_characters
        )
        base: list[list[_Piece]] = []
        current: list[_Piece] = []
        for block in document.blocks:
            pieces = self._split_block(block, payload_limit)
            atomic = block.block_type in ATOMIC_BLOCK_TYPES
            if atomic and current:
                base.append(current)
                current = []
            for piece in pieces:
                section_changed = bool(
                    current and current[-1].block.section_path != block.section_path
                )
                if section_changed or not self._fits(current, piece, payload_limit):
                    if current:
                        base.append(current)
                    current = []
                current.append(piece)
                if atomic:
                    base.append(current)
                    current = []
        if current:
            base.append(current)
        if not base:
            raise ChunkingError("CHUNK_NO_TEXT", "No nonempty chunks were produced.")

        with_overlap: list[list[_Piece]] = [base[0]]
        for pieces in base[1:]:
            previous = with_overlap[-1]
            prefix = self._overlap_piece(previous, pieces)
            with_overlap.append(([prefix] if prefix is not None else []) + pieces)
        return with_overlap

    def _split_block(self, block: NormalizedBlock, limit: int) -> list[_Piece]:
        if len(block.text) <= self.config.max_chunk_characters and (
            block.block_type in ATOMIC_BLOCK_TYPES
        ):
            return [_Piece(block, 0, len(block.text))]
        pieces: list[_Piece] = []
        start = 0
        while start < len(block.text):
            hard_end = min(start + limit, len(block.text))
            end = self._preferred_break(block.text, start, hard_end)
            if end <= start:
                end = hard_end
            pieces.append(_Piece(block, start, end))
            start = end
            while start < len(block.text) and block.text[start].isspace():
                start += 1
        return pieces

    @staticmethod
    def _preferred_break(text: str, start: int, hard_end: int) -> int:
        if hard_end == len(text):
            return hard_end
        window = text[start:hard_end]
        sentence_breaks = [
            match.end() for match in BREAK_AFTER_SENTENCE.finditer(window)
        ]
        if sentence_breaks:
            return start + sentence_breaks[-1]
        whitespace = max(window.rfind(" "), window.rfind("\n"), window.rfind("\t"))
        return start + whitespace + 1 if whitespace >= 0 else hard_end

    def _fits(self, pieces: list[_Piece], candidate: _Piece, limit: int) -> bool:
        if not pieces:
            return len(candidate.text) <= self.config.max_chunk_characters
        projected = (
            len(self._render(pieces))
            + len(self._separator_between(pieces[-1], candidate))
            + len(candidate.text)
        )
        return projected <= limit

    def _overlap_piece(
        self,
        previous: list[_Piece],
        current: list[_Piece],
    ) -> _Piece | None:
        if not previous or not current or self.config.overlap_characters == 0:
            return None
        if previous[-1].block.section_path != current[0].block.section_path:
            return None
        available = self.config.max_chunk_characters - len(self._render(current))
        budget = min(self.config.overlap_characters, available)
        previous_piece = previous[-1]
        if budget <= 0 or not previous_piece.text:
            return None
        start = max(previous_piece.start, previous_piece.end - budget)
        return _Piece(previous_piece.block, start, previous_piece.end)

    def _render(self, pieces: list[_Piece]) -> str:
        rendered = pieces[0].text
        for previous, current in zip(pieces, pieces[1:], strict=False):
            rendered += self._separator_between(previous, current) + current.text
        return rendered

    def _separator_between(self, previous: _Piece, current: _Piece) -> str:
        if previous.block.block_index == current.block.block_index:
            return ""
        return self.config.separator

    def _create_chunk(
        self,
        document: NormalizedDocument,
        pieces: list[_Piece],
        *,
        chunk_index: int,
        configuration_hash: str,
        source_storage_version: str | None,
    ) -> DocumentChunk:
        text = self._render(pieces)
        if not text.strip():
            raise ChunkingError("CHUNK_NO_TEXT", "An empty chunk was produced.")
        if len(text) > self.config.max_chunk_characters:
            raise ChunkingError(
                "CHUNK_INVALID_CONFIGURATION",
                "Chunk output exceeded the configured character limit.",
            )
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        identity = ":".join(
            (
                str(document.document_id),
                source_storage_version or "unversioned",
                self.version,
                configuration_hash,
                str(chunk_index),
                content_hash,
            )
        )
        spans = tuple(
            ChunkSourceSpan(
                source_block_index=piece.block.block_index,
                normalized_start_offset=piece.start,
                normalized_end_offset=piece.end,
                page_number=piece.block.page_number,
                bounding_box=piece.block.bounding_box,
            )
            for piece in pieces
        )
        pages = tuple(
            sorted(
                {
                    piece.block.page_number
                    for piece in pieces
                    if piece.block.page_number is not None
                }
            )
        )
        return DocumentChunk(
            chunk_index=chunk_index,
            chunk_id=uuid5(NAMESPACE_URL, identity),
            text=text,
            section_path=pieces[-1].block.section_path,
            source_spans=spans,
            page_numbers=pages,
            character_count=len(text),
            content_hash=content_hash,
        )
