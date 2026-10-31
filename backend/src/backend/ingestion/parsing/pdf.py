"""Phase-1 parser for digital PDFs; scanned PDFs require future OCR."""

import re
from collections.abc import Callable, Sequence
from io import BytesIO
from typing import Protocol

import pypdf
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from backend.ingestion.parsing.interface import ParseError
from backend.ingestion.parsing.models import (
    ParsedBlock,
    ParsedDocument,
    ParseStatistics,
)
from backend.ingestion.stages import ValidatedSource

PARAGRAPH_SEPARATOR = re.compile(r"(?:\r?\n)[\t ]*(?:\r?\n)+")


class PdfPage(Protocol):
    def extract_text(self, *args, **kwargs) -> str | None: ...


class PdfDocument(Protocol):
    @property
    def is_encrypted(self) -> bool: ...

    @property
    def pages(self) -> Sequence[PdfPage]: ...


ReaderFactory = Callable[[BytesIO], PdfDocument]


class PdfParser:
    def __init__(
        self,
        reader_factory: ReaderFactory = PdfReader,
    ) -> None:
        self._reader_factory = reader_factory

    @property
    def name(self) -> str:
        return "pypdf"

    @property
    def version(self) -> str:
        return f"1+pypdf-{pypdf.__version__}"

    @property
    def content_types(self) -> frozenset[str]:
        return frozenset({"application/pdf"})

    def parse(self, source: ValidatedSource) -> ParsedDocument:
        if source.content_type not in self.content_types:
            raise ParseError(
                "PARSE_UNSUPPORTED_TYPE",
                f"PdfParser does not support {source.content_type}.",
            )
        try:
            reader = self._reader_factory(BytesIO(source.content))
            if reader.is_encrypted:
                raise ParseError(
                    "PARSE_PASSWORD_PROTECTED",
                    "Password-protected PDFs are not supported.",
                )
            page_count = len(reader.pages)
            blocks = self._extract_blocks(reader.pages)
        except ParseError:
            raise
        except (PyPdfError, OSError, ValueError) as exc:
            raise ParseError(
                "PARSE_CORRUPT_DOCUMENT",
                "PDF source could not be parsed.",
            ) from exc

        if not blocks:
            code = "PARSE_OCR_REQUIRED" if page_count else "PARSE_NO_TEXT"
            message = (
                "PDF contains no extractable text and may require OCR."
                if page_count
                else "PDF contains no pages or useful text."
            )
            raise ParseError(code, message)
        return ParsedDocument(
            document_id=source.document_id,
            source_storage_version=source.storage_version,
            parser_name=self.name,
            parser_version=self.version,
            content_type=source.content_type,
            page_count=page_count,
            blocks=blocks,
            statistics=ParseStatistics(
                block_count=len(blocks),
                extracted_character_count=sum(len(block.text) for block in blocks),
            ),
        )

    @staticmethod
    def _extract_blocks(pages: Sequence[PdfPage]) -> tuple[ParsedBlock, ...]:
        blocks: list[ParsedBlock] = []
        for page_number, page in enumerate(pages, start=1):
            text = page.extract_text(
                extraction_mode="layout",
                layout_mode_space_vertically=False,
            )
            paragraphs = [
                paragraph.strip()
                for paragraph in PARAGRAPH_SEPARATOR.split(text or "")
                if paragraph.strip()
            ]
            for paragraph in paragraphs:
                blocks.append(
                    ParsedBlock(
                        block_index=len(blocks),
                        block_type="paragraph",
                        text=paragraph,
                        page_number=page_number,
                    )
                )
        return tuple(blocks)
