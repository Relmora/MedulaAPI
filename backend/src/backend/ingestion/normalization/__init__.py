"""Deterministic document-normalization contracts and implementation."""

from backend.ingestion.normalization.interface import NormalizationError, Normalizer
from backend.ingestion.normalization.models import (
    NORMALIZED_DOCUMENT_SCHEMA_VERSION,
    NormalizationStatistics,
    NormalizedBlock,
    NormalizedDocument,
)
from backend.ingestion.normalization.normalizer import DeterministicNormalizer

__all__ = [
    "NORMALIZED_DOCUMENT_SCHEMA_VERSION",
    "DeterministicNormalizer",
    "NormalizedBlock",
    "NormalizedDocument",
    "NormalizationError",
    "NormalizationStatistics",
    "Normalizer",
]
