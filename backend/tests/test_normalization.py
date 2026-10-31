import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.ingestion.normalization import (
    DeterministicNormalizer,
    NormalizationError,
    NormalizationStatistics,
    NormalizedBlock,
    NormalizedDocument,
)
from backend.ingestion.parsing import ParsedBlock, ParsedDocument, ParseStatistics
from backend.ingestion.stages import NormalizeStage
from backend.object_storage.fake import FakeObjectStorage


def parsed_document(*blocks: ParsedBlock) -> ParsedDocument:
    return ParsedDocument(
        document_id=uuid4(),
        source_storage_version="source-123",
        parser_name="test",
        parser_version="1",
        content_type="text/plain",
        blocks=blocks,
        warnings=("parser warning",),
        statistics=ParseStatistics(
            block_count=len(blocks),
            extracted_character_count=sum(len(block.text) for block in blocks),
        ),
    )


def test_normalizer_applies_conservative_rules_and_preserves_provenance():
    document = parsed_document(
        ParsedBlock(
            block_index=0,
            block_type="paragraph",
            text="  Cafe\u0301\u00a0\t value\r\nnext\x00 line  ",
            page_number=2,
            section_path=("Section",),
            metadata={"kind": "body"},
        ),
        ParsedBlock(
            block_index=1,
            block_type="code",
            text="\r\n  value\t =  1  \r\n",
        ),
    )

    normalized = DeterministicNormalizer().normalize(document)

    assert normalized.schema_version == 1
    assert normalized.parsed_schema_version == document.schema_version
    assert normalized.normalizer_name == "deterministic"
    assert normalized.normalizer_version == "1"
    assert normalized.warnings == ("parser warning",)
    assert normalized.blocks[0].text == "Café value\nnext line"
    assert normalized.blocks[0].source_block_index == 0
    assert normalized.blocks[0].page_number == 2
    assert normalized.blocks[0].section_path == ("Section",)
    assert normalized.blocks[0].metadata == {"kind": "body"}
    assert normalized.blocks[1].text == "  value\t =  1  "
    assert normalized.statistics.normalized_character_count == sum(
        len(block.text) for block in normalized.blocks
    )


def test_normalizer_removes_empty_blocks_and_reindexes_output():
    normalized = DeterministicNormalizer().normalize(
        parsed_document(
            ParsedBlock(block_index=0, block_type="paragraph", text="\x00"),
            ParsedBlock(block_index=1, block_type="paragraph", text=" useful "),
        )
    )

    assert len(normalized.blocks) == 1
    assert normalized.blocks[0].block_index == 0
    assert normalized.blocks[0].source_block_index == 1
    assert normalized.statistics.source_block_count == 2
    assert normalized.statistics.removed_block_count == 1


def test_normalizer_rejects_document_without_useful_text():
    with pytest.raises(NormalizationError) as raised:
        DeterministicNormalizer().normalize(
            parsed_document(
                ParsedBlock(block_index=0, block_type="paragraph", text="\x00")
            )
        )

    assert raised.value.code == "NORMALIZE_NO_TEXT"


def test_normalizer_does_not_keep_whitespace_only_code_as_useful_text():
    with pytest.raises(NormalizationError) as raised:
        DeterministicNormalizer().normalize(
            parsed_document(
                ParsedBlock(block_index=0, block_type="code", text=" \t\n  ")
            )
        )

    assert raised.value.code == "NORMALIZE_NO_TEXT"


def test_normalized_document_validates_statistics():
    block = NormalizedBlock(
        block_index=0,
        source_block_index=0,
        block_type="paragraph",
        text="text",
    )

    with pytest.raises(ValidationError, match="normalized_character_count"):
        NormalizedDocument(
            document_id=uuid4(),
            parsed_schema_version=1,
            normalizer_name="test",
            normalizer_version="1",
            blocks=(block,),
            statistics=NormalizationStatistics(
                source_block_count=1,
                block_count=1,
                removed_block_count=0,
                normalized_character_count=3,
            ),
        )


def test_normalize_stage_uploads_versioned_json_artifact():
    storage = FakeObjectStorage()
    parsed = parsed_document(
        ParsedBlock(block_index=0, block_type="paragraph", text=" text ")
    )

    artifact = NormalizeStage(DeterministicNormalizer(), storage).execute(parsed)

    expected_key = (
        f"documents/{parsed.document_id}/normalized/source-123/"
        "deterministic-v1.json"
    )
    assert artifact.object_key == expected_key
    assert artifact.storage_version == "1"
    assert artifact.document.blocks[0].text == "text"
    stored = json.loads(storage.object_contents[expected_key])
    assert stored["schema_version"] == 1
    assert stored["normalizer_version"] == "1"
    assert storage.objects[expected_key].content_type == "application/json"
