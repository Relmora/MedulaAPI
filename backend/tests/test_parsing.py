from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.ingestion.parsing import (
    ParsedBlock,
    ParsedDocument,
    ParseError,
    ParserRegistry,
    ParseStatistics,
    PlainTextParser,
)
from backend.ingestion.stages import ValidatedSource


def source(content: bytes, *, content_type: str = "text/plain") -> ValidatedSource:
    return ValidatedSource(
        document_id=uuid4(),
        original_filename="notes.txt",
        content_type=content_type,
        storage_version="123",
        content=content,
    )


def test_plain_text_parser_produces_ordered_paragraph_blocks():
    parsed = PlainTextParser().parse(
        source(b"\xef\xbb\xbfFirst line\ncontinues here.\n\nSecond paragraph.\n")
    )

    assert parsed.schema_version == 1
    assert parsed.parser_name == "plain_text"
    assert parsed.parser_version == "1"
    assert parsed.source_storage_version == "123"
    assert [block.block_index for block in parsed.blocks] == [0, 1]
    assert [block.block_type for block in parsed.blocks] == [
        "paragraph",
        "paragraph",
    ]
    assert [block.text for block in parsed.blocks] == [
        "First line\ncontinues here.",
        "Second paragraph.",
    ]
    assert parsed.statistics.block_count == 2
    assert parsed.statistics.extracted_character_count == sum(
        len(block.text) for block in parsed.blocks
    )


@pytest.mark.parametrize("content", [b"", b" \n\t\n "])
def test_plain_text_parser_rejects_empty_text(content):
    with pytest.raises(ParseError) as raised:
        PlainTextParser().parse(source(content))

    assert raised.value.code == "PARSE_NO_TEXT"


def test_plain_text_parser_rejects_wrong_type_and_invalid_encoding():
    parser = PlainTextParser()

    with pytest.raises(ParseError) as wrong_type:
        parser.parse(source(b"text", content_type="text/markdown"))
    assert wrong_type.value.code == "PARSE_UNSUPPORTED_TYPE"

    with pytest.raises(ParseError) as invalid_encoding:
        parser.parse(source(b"\xff"))
    assert invalid_encoding.value.code == "PARSE_TEXT_ENCODING_INVALID"


def test_registry_routes_by_normalized_content_type():
    parser = PlainTextParser()
    registry = ParserRegistry([parser])

    assert registry.resolve(" TEXT/PLAIN ") is parser
    with pytest.raises(ParseError) as unsupported:
        registry.resolve("application/pdf")
    assert unsupported.value.code == "PARSE_UNSUPPORTED_TYPE"


def test_registry_rejects_duplicate_content_type():
    registry = ParserRegistry([PlainTextParser()])

    with pytest.raises(ValueError, match="already registered"):
        registry.register(PlainTextParser())


def test_parsed_document_enforces_ordered_indexes_and_statistics():
    block = ParsedBlock(
        block_index=1,
        block_type="paragraph",
        text="text",
    )

    with pytest.raises(ValidationError, match="contiguous and ordered"):
        ParsedDocument(
            document_id=uuid4(),
            parser_name="test",
            parser_version="1",
            content_type="text/plain",
            blocks=(block,),
            statistics=ParseStatistics(
                block_count=1,
                extracted_character_count=4,
            ),
        )
