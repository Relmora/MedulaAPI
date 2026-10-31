from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.ingestion.parsing import (
    MarkdownParser,
    ParsedBlock,
    ParsedDocument,
    ParseError,
    ParserRegistry,
    ParseStatistics,
    PdfParser,
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


def test_markdown_parser_preserves_structure_and_heading_path():
    content = b"""# Guide

Read the [documentation](https://example.invalid).

## Setup

- Install the package
- Configure storage

```python
print("ready")
```

| Name | Value |
| --- | --- |
| mode | safe |
"""

    parsed = MarkdownParser().parse(source(content, content_type="text/markdown"))

    assert [block.block_type for block in parsed.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "list_item",
        "list_item",
        "code",
        "table",
    ]
    assert parsed.blocks[0].section_path == ("Guide",)
    assert parsed.blocks[1].text == "Read the documentation."
    assert parsed.blocks[2].section_path == ("Guide", "Setup")
    assert parsed.blocks[3].section_path == ("Guide", "Setup")
    assert parsed.blocks[3].metadata == {"list_depth": 1}
    assert parsed.blocks[5].metadata == {"language": "python"}
    assert parsed.blocks[6].text == "| Name | Value |\n| mode | safe |"


@pytest.mark.parametrize("content", [b"", b"<!-- comment only -->"])
def test_markdown_parser_rejects_documents_without_useful_text(content):
    with pytest.raises(ParseError) as raised:
        MarkdownParser().parse(source(content, content_type="text/markdown"))

    assert raised.value.code == "PARSE_NO_TEXT"


class FakePdfPage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = []

    def extract_text(self, *args, **kwargs) -> str:
        self.calls.append((args, kwargs))
        return self.text


class FakePdfDocument:
    def __init__(self, pages, *, encrypted: bool = False) -> None:
        self._pages = pages
        self._encrypted = encrypted

    @property
    def is_encrypted(self) -> bool:
        return self._encrypted

    @property
    def pages(self):
        return self._pages


def test_pdf_parser_extracts_ordered_page_paragraphs():
    first_page = FakePdfPage("First paragraph.\n\nSecond paragraph.")
    second_page = FakePdfPage("Third paragraph.")
    parser = PdfParser(
        reader_factory=lambda _: FakePdfDocument([first_page, second_page])
    )

    parsed = parser.parse(source(b"%PDF-fake", content_type="application/pdf"))

    assert parsed.parser_name == "pypdf"
    assert parsed.parser_version.startswith("1+pypdf-")
    assert parsed.page_count == 2
    assert [block.text for block in parsed.blocks] == [
        "First paragraph.",
        "Second paragraph.",
        "Third paragraph.",
    ]
    assert [block.page_number for block in parsed.blocks] == [1, 1, 2]
    assert first_page.calls == [
        (
            (),
            {
                "extraction_mode": "layout",
                "layout_mode_space_vertically": False,
            },
        )
    ]


def test_pdf_parser_rejects_encrypted_and_scanned_documents():
    encrypted = PdfParser(reader_factory=lambda _: FakePdfDocument([], encrypted=True))
    with pytest.raises(ParseError) as password_error:
        encrypted.parse(source(b"%PDF-fake", content_type="application/pdf"))
    assert password_error.value.code == "PARSE_PASSWORD_PROTECTED"

    scanned = PdfParser(reader_factory=lambda _: FakePdfDocument([FakePdfPage("")]))
    with pytest.raises(ParseError) as ocr_error:
        scanned.parse(source(b"%PDF-fake", content_type="application/pdf"))
    assert ocr_error.value.code == "PARSE_OCR_REQUIRED"


def test_registry_routes_all_phase_one_content_types():
    plain_text = PlainTextParser()
    markdown = MarkdownParser()
    pdf = PdfParser(reader_factory=lambda _: FakePdfDocument([]))
    registry = ParserRegistry([plain_text, markdown, pdf])

    assert registry.resolve("text/plain") is plain_text
    assert registry.resolve("text/markdown") is markdown
    assert registry.resolve("application/pdf") is pdf
