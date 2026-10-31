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
"""

import os
import socket
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.database import create_database_engine
from backend.ingestion import IngestionJobClaimer, IngestionPipeline, IngestionWorker
from backend.ingestion.parsing import (
    MarkdownParser,
    ParserRegistry,
    PdfParser,
    PlainTextParser,
)
from backend.ingestion.rabbitmq import RabbitMQIngestionConsumer
from backend.ingestion.stages import ParseStage, SourceValidator
from backend.logging import configure_logging
from backend.object_storage.gcs import GCSObjectStorage


def create_worker_id() -> str:
    hostname = socket.gethostname().strip() or "unknown-host"
    return f"{hostname}:{os.getpid()}:{uuid4()}"


def build_parser_registry() -> ParserRegistry:
    return ParserRegistry([PdfParser(), MarkdownParser(), PlainTextParser()])


def build_consumer(settings: Settings) -> RabbitMQIngestionConsumer:
    engine = create_database_engine(settings)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    storage = GCSObjectStorage(
        bucket=settings.storage_bucket,
        project_id=settings.gcp_project_id,
    )
    registry = build_parser_registry()
    worker = IngestionWorker(
        IngestionJobClaimer(
            sessions,
            lease_ttl=timedelta(seconds=settings.ingestion_worker_lease_seconds),
        ),
        worker_id=create_worker_id(),
        pipeline=IngestionPipeline(
            sessions,
            SourceValidator(sessions, storage),
            ParseStage(registry, storage),
        ),
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
