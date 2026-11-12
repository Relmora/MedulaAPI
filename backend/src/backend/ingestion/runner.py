"""Production composition and command-line entry point for ingestion workers.
connects all the below things together in a single process:
RabbitMQ consumer
→ IngestionWorker
→ IngestionJobClaimer
→ SourceValidator
→ ParseStage
→ ParserRegistry
→ PDF / Markdown / Plain-text parser
→ GCS

Load settings
     ↓
Create database connection
     ↓
Create GCS storage client
     ↓
Create every pipeline stage
     ↓
Connect stages to IngestionPipeline
     ↓
Connect pipeline to IngestionWorker
     ↓
Start consuming RabbitMQ messages
"""

import os
import socket
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.database import create_database_engine
from backend.ingestion import IngestionJobClaimer, IngestionPipeline, IngestionWorker
from backend.ingestion.chunking import BlockAwareChunker
from backend.ingestion.embedding import DocumentEmbedder, VertexAIEmbeddingProvider
from backend.ingestion.graph_storage import PostgresGraphStore
from backend.ingestion.indexing import PgVectorIndex
from backend.ingestion.lease import IngestionLeaseHeartbeat
from backend.ingestion.normalization import DeterministicNormalizer
from backend.ingestion.parsing import (
    MarkdownParser,
    ParserRegistry,
    PdfParser,
    PlainTextParser,
)
from backend.ingestion.rabbitmq import RabbitMQIngestionConsumer
from backend.ingestion.relation_extraction import (
    DocumentRelationExtractor,
    VertexAIRelationProvider,
)
from backend.ingestion.stages import (
    ChunkStage,
    EmbedStage,
    GraphStoreStage,
    IndexStage,
    NormalizeStage,
    ParseStage,
    RelationExtractStage,
    SourceValidator,
)
from backend.logging import configure_logging
from backend.object_storage.gcs import GCSObjectStorage


def create_worker_id() -> str:
    hostname = socket.gethostname().strip() or "unknown-host"
    return f"{hostname}:{os.getpid()}:{uuid4()}"


def build_parser_registry() -> ParserRegistry:
    return ParserRegistry([PdfParser(), MarkdownParser(), PlainTextParser()])


def build_chunker() -> BlockAwareChunker:
    return BlockAwareChunker()


def build_embedder(settings: Settings) -> DocumentEmbedder:
    if not settings.gcp_project_id or not settings.gcp_project_id.strip():
        raise ValueError("GCP_PROJECT_ID must be configured for Vertex AI embeddings")
    provider = VertexAIEmbeddingProvider(
        project_id=settings.gcp_project_id,
        location=settings.embedding_location,
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
    return DocumentEmbedder(provider, batch_size=settings.embedding_batch_size)


def build_relation_extractor(settings: Settings) -> DocumentRelationExtractor:
    if not settings.gcp_project_id or not settings.gcp_project_id.strip():
        raise ValueError(
            "GCP_PROJECT_ID must be configured for Vertex AI relation extraction"
        )
    provider = VertexAIRelationProvider(
        project_id=settings.gcp_project_id,
        location=settings.relation_extraction_location,
        model_name=settings.relation_extraction_model,
        timeout_seconds=settings.relation_extraction_timeout_seconds,
    )
    return DocumentRelationExtractor(provider)


def build_consumer(settings: Settings) -> RabbitMQIngestionConsumer:
    engine = create_database_engine(settings)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    storage = GCSObjectStorage(
        bucket=settings.storage_bucket,
        project_id=settings.gcp_project_id,
    )
    registry = build_parser_registry()
    lease_ttl = timedelta(seconds=settings.ingestion_worker_lease_seconds)
    worker = IngestionWorker(
        IngestionJobClaimer(
            sessions,
            lease_ttl=lease_ttl,
        ),
        worker_id=create_worker_id(),
        pipeline=IngestionPipeline(
            sessions,
            SourceValidator(sessions, storage),
            ParseStage(registry, storage),
            NormalizeStage(DeterministicNormalizer(), storage),
            ChunkStage(build_chunker(), storage),
            EmbedStage(build_embedder(settings), storage),
            IndexStage(PgVectorIndex(sessions), storage),
            RelationExtractStage(build_relation_extractor(settings), storage),
            GraphStoreStage(PostgresGraphStore(sessions), storage),
        ),
        lease_heartbeat=IngestionLeaseHeartbeat(sessions, lease_ttl=lease_ttl),
    )
    return RabbitMQIngestionConsumer(settings, worker)


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    if not settings.storage_bucket.strip():
        raise ValueError("STORAGE_BUCKET must be configured")
    consumer = build_consumer(settings)
    try:
        consumer.run()
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
