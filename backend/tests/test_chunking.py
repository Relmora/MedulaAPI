import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.ingestion.chunking import (
    BlockAwareChunker,
    ChunkingConfig,
    ChunkingError,
)
from backend.ingestion.normalization import (
    NormalizationStatistics,
    NormalizedBlock,
    NormalizedDocument,
)
from backend.ingestion.parsing import BoundingBox
from backend.ingestion.stages import ChunkStage, NormalizedArtifact
from backend.object_storage.fake import FakeObjectStorage


def normalized_document(*blocks: NormalizedBlock) -> NormalizedDocument:
    return NormalizedDocument(
        document_id=uuid4(),
        source_storage_version="original-1",
        parsed_schema_version=1,
        normalizer_name="deterministic",
        normalizer_version="1",
        blocks=blocks,
        warnings=("normalization warning",),
        statistics=NormalizationStatistics(
            source_block_count=len(blocks),
            block_count=len(blocks),
            removed_block_count=0,
            normalized_character_count=sum(len(block.text) for block in blocks),
        ),
    )


def test_chunker_aggregates_prose_and_preserves_exact_provenance():
    bbox = BoundingBox(left=1, top=2, right=10, bottom=20)
    document = normalized_document(
        NormalizedBlock(
            block_index=0,
            source_block_index=3,
            block_type="paragraph",
            text="First paragraph.",
            page_number=1,
            section_path=("Intro",),
            bounding_box=bbox,
        ),
        NormalizedBlock(
            block_index=1,
            source_block_index=4,
            block_type="paragraph",
            text="Second paragraph.",
            page_number=2,
            section_path=("Intro",),
        ),
    )

    result = BlockAwareChunker(
        ChunkingConfig(max_chunk_characters=100, overlap_characters=10)
    ).chunk(
        document,
        source_object_key="documents/id/normalized/1.json",
        source_storage_version="7",
    )

    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.text == "First paragraph.\n\nSecond paragraph."
    assert chunk.section_path == ("Intro",)
    assert chunk.page_numbers == (1, 2)
    assert [span.source_block_index for span in chunk.source_spans] == [0, 1]
    assert chunk.source_spans[0].normalized_start_offset == 0
    assert chunk.source_spans[0].normalized_end_offset == len("First paragraph.")
    assert chunk.source_spans[0].bounding_box == bbox
    assert result.statistics.source_block_count == 2
    assert result.statistics.chunk_count == 1


def test_chunker_splits_at_boundaries_with_bounded_deterministic_overlap():
    text = "Alpha beta gamma. Delta epsilon zeta. Eta theta iota."
    document = normalized_document(
        NormalizedBlock(
            block_index=0,
            source_block_index=0,
            block_type="paragraph",
            text=text,
            section_path=("Body",),
        )
    )
    chunker = BlockAwareChunker(
        ChunkingConfig(max_chunk_characters=30, overlap_characters=6)
    )

    first = chunker.chunk(
        document,
        source_object_key="normalized.json",
        source_storage_version="1",
    )
    second = chunker.chunk(
        document,
        source_object_key="normalized.json",
        source_storage_version="1",
    )

    assert first == second
    assert len(first.chunks) >= 2
    assert all(chunk.character_count <= 30 for chunk in first.chunks)
    assert [chunk.chunk_index for chunk in first.chunks] == list(
        range(len(first.chunks))
    )
    for previous, current in zip(first.chunks, first.chunks[1:], strict=False):
        overlap_span = current.source_spans[0]
        overlap_text = text[
            overlap_span.normalized_start_offset : overlap_span.normalized_end_offset
        ]
        assert previous.text.endswith(overlap_text)
        assert current.text.startswith(overlap_text)


def test_chunker_preserves_sections_and_atomic_code_blocks():
    code = "def answer():\n    return 42"
    document = normalized_document(
        NormalizedBlock(
            block_index=0,
            source_block_index=0,
            block_type="paragraph",
            text="Introduction text.",
            section_path=("Intro",),
        ),
        NormalizedBlock(
            block_index=1,
            source_block_index=1,
            block_type="code",
            text=code,
            section_path=("Code",),
        ),
        NormalizedBlock(
            block_index=2,
            source_block_index=2,
            block_type="paragraph",
            text="Conclusion text.",
            section_path=("Conclusion",),
        ),
    )

    result = BlockAwareChunker(
        ChunkingConfig(max_chunk_characters=40, overlap_characters=5)
    ).chunk(
        document,
        source_object_key="normalized.json",
        source_storage_version="1",
    )

    assert [chunk.section_path for chunk in result.chunks] == [
        ("Intro",),
        ("Code",),
        ("Conclusion",),
    ]
    assert result.chunks[1].text == code


def test_chunk_stage_uploads_versioned_json_artifact():
    storage = FakeObjectStorage()
    document = normalized_document(
        NormalizedBlock(
            block_index=0,
            source_block_index=0,
            block_type="paragraph",
            text="Chunk this normalized text.",
        )
    )
    normalized = NormalizedArtifact(
        document=document,
        object_key=f"documents/{document.document_id}/normalized/source/deterministic-v1.json",
        storage_version="1",
    )
    storage.write_object(
        normalized.object_key,
        document.model_dump_json().encode(),
        content_type="application/json",
    )

    artifact = ChunkStage(BlockAwareChunker(), storage).execute(normalized)

    assert artifact.storage_version == "1"
    assert artifact.object_key.startswith(
        f"documents/{document.document_id}/chunked/1/block-aware-v1-"
    )
    stored = json.loads(storage.object_contents[artifact.object_key])
    assert stored["schema_version"] == 1
    assert stored["source_normalized_storage_version"] == "1"
    assert stored["chunks"][0]["text"] == "Chunk this normalized text."
    assert storage.objects[artifact.object_key].content_type == "application/json"


def test_chunk_stage_rejects_a_corrupt_normalized_artifact():
    storage = FakeObjectStorage()
    document = normalized_document(
        NormalizedBlock(
            block_index=0,
            source_block_index=0,
            block_type="paragraph",
            text="Valid in-memory text.",
        )
    )
    object_key = f"documents/{document.document_id}/normalized/source.json"
    storage.write_object(
        object_key,
        b"not-json",
        content_type="application/json",
    )
    normalized = NormalizedArtifact(
        document=document,
        object_key=object_key,
        storage_version="1",
    )

    with pytest.raises(ChunkingError) as raised:
        ChunkStage(BlockAwareChunker(), storage).execute(normalized)

    assert raised.value.code == "CHUNK_PROVENANCE_INVALID"


def test_chunker_rejects_missing_normalized_artifact_provenance():
    document = normalized_document(
        NormalizedBlock(
            block_index=0,
            source_block_index=0,
            block_type="paragraph",
            text="Text",
        )
    )

    with pytest.raises(ChunkingError) as raised:
        BlockAwareChunker().chunk(
            document,
            source_object_key=" ",
            source_storage_version="1",
        )

    assert raised.value.code == "CHUNK_PROVENANCE_INVALID"


@pytest.mark.parametrize(
    "values",
    [
        {"max_chunk_characters": 0},
        {"max_chunk_characters": 20, "overlap_characters": 20},
        {"max_chunk_characters": 20, "overlap_characters": 21},
    ],
)
def test_chunking_configuration_rejects_invalid_limits(values):
    with pytest.raises(ValidationError):
        ChunkingConfig(**values)
