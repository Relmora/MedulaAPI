from backend.ingestion.chunking import BlockAwareChunker
from backend.ingestion.parsing import MarkdownParser, PdfParser, PlainTextParser
from backend.ingestion.runner import build_chunker, build_parser_registry


def test_production_registry_contains_all_phase_one_parsers():
    registry = build_parser_registry()

    assert isinstance(registry.resolve("application/pdf"), PdfParser)
    assert isinstance(registry.resolve("text/markdown"), MarkdownParser)
    assert isinstance(registry.resolve("text/plain"), PlainTextParser)


def test_production_worker_uses_the_phase_one_chunker_defaults():
    chunker = build_chunker()

    assert isinstance(chunker, BlockAwareChunker)
    assert chunker.config.max_chunk_characters == 1500
    assert chunker.config.overlap_characters == 200
    assert chunker.config.separator == "\n\n"
