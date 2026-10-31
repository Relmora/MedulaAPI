from backend.ingestion.parsing import MarkdownParser, PdfParser, PlainTextParser
from backend.ingestion.runner import build_parser_registry


def test_production_registry_contains_all_phase_one_parsers():
    registry = build_parser_registry()

    assert isinstance(registry.resolve("application/pdf"), PdfParser)
    assert isinstance(registry.resolve("text/markdown"), MarkdownParser)
    assert isinstance(registry.resolve("text/plain"), PlainTextParser)
