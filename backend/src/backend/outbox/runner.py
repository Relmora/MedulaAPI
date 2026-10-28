"""Command-line loop that publishes due transactional outbox events."""

import os
import signal
import socket
from datetime import timedelta
from threading import Event
from types import FrameType
from typing import Protocol
from uuid import uuid4

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.database import create_database_engine
from backend.logging import configure_logging, get_logger
from backend.outbox.publisher import (
    MAX_PUBLISHER_ID_LENGTH,
    OutboxPublisher,
    PublishBatchResult,
)
from backend.outbox.rabbitmq import RabbitMQConfirmingTransport

logger = get_logger(__name__)


class BatchPublisher(Protocol):
    def publish_batch(self) -> PublishBatchResult: ...


class ClosableTransport(Protocol):
    def close(self) -> None: ...


class DisposableEngine(Protocol):
    def dispose(self) -> None: ...


def create_publisher_id() -> str:
    """Create an identity unique to one publisher process lifetime."""
    hostname = socket.gethostname().strip() or "unknown-host"
    suffix = f":{os.getpid()}:{uuid4()}"
    hostname = hostname[: MAX_PUBLISHER_ID_LENGTH - len(suffix)]
    return f"{hostname}{suffix}"


class OutboxPublisherRunner:
    """Run publisher batches until shutdown, with bounded infrastructure backoff."""

    def __init__(
        self,
        publisher: BatchPublisher,
        transport: ClosableTransport,
        engine: DisposableEngine,
        *,
        publisher_id: str,
        stop_event: Event,
        poll_seconds: float,
        error_backoff_seconds: float,
        max_error_backoff_seconds: float,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if error_backoff_seconds <= 0:
            raise ValueError("error_backoff_seconds must be positive")
        if max_error_backoff_seconds < error_backoff_seconds:
            raise ValueError(
                "max_error_backoff_seconds must be at least error_backoff_seconds"
            )

        self._publisher = publisher
        self._transport = transport
        self._engine = engine
        self._publisher_id = publisher_id
        self._stop_event = stop_event
        self._poll_seconds = poll_seconds
        self._error_backoff_seconds = error_backoff_seconds
        self._max_error_backoff_seconds = max_error_backoff_seconds

    def run(self) -> None:
        """Publish batches until a shutdown signal sets the stop event."""
        consecutive_failures = 0
        logger.info(
            "Outbox publisher started",
            extra={
                "event": "outbox.publisher.started",
                "publisher_id": self._publisher_id,
            },
        )
        try:
            while not self._stop_event.is_set():
                try:
                    result = self._publisher.publish_batch()
                except Exception:
                    consecutive_failures += 1
                    retry_seconds = min(
                        self._error_backoff_seconds * (2 ** (consecutive_failures - 1)),
                        self._max_error_backoff_seconds,
                    )
                    logger.exception(
                        "Outbox publisher batch failed",
                        extra={
                            "event": "outbox.batch.failed",
                            "publisher_id": self._publisher_id,
                            "failure_count": consecutive_failures,
                            "retry_seconds": retry_seconds,
                        },
                    )
                    self._stop_event.wait(retry_seconds)
                    continue

                consecutive_failures = 0
                self._log_batch(result)
                if result.claimed == 0 and not self._stop_event.is_set():
                    self._stop_event.wait(self._poll_seconds)
        finally:
            try:
                self._transport.close()
            except Exception:
                logger.exception(
                    "Outbox publisher transport cleanup failed",
                    extra={
                        "event": "outbox.publisher.cleanup_failed",
                        "publisher_id": self._publisher_id,
                    },
                )
            try:
                self._engine.dispose()
            except Exception:
                logger.exception(
                    "Outbox publisher database cleanup failed",
                    extra={
                        "event": "outbox.publisher.cleanup_failed",
                        "publisher_id": self._publisher_id,
                    },
                )
            logger.info(
                "Outbox publisher stopped",
                extra={
                    "event": "outbox.publisher.stopped",
                    "publisher_id": self._publisher_id,
                },
            )

    def _log_batch(self, result: PublishBatchResult) -> None:
        if result.claimed == 0:
            return
        extra = {
            "event": "outbox.batch.completed",
            "publisher_id": self._publisher_id,
            "claimed": result.claimed,
            "published": result.published,
            "failed": result.failed,
            "lost_claims": result.lost_claims,
        }
        if result.failed or result.lost_claims:
            logger.warning(
                "Outbox publisher batch completed with failures", extra=extra
            )
        else:
            logger.info("Outbox publisher batch completed", extra=extra)


def _install_signal_handlers(stop_event: Event) -> None:
    def request_shutdown(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


def build_runner(settings: Settings, stop_event: Event) -> OutboxPublisherRunner:
    """Wire production database, transport, publisher, and runner objects."""
    engine: Engine = create_database_engine(settings)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    transport = RabbitMQConfirmingTransport(settings)
    publisher_id = create_publisher_id()
    publisher = OutboxPublisher(
        sessions,
        transport,
        publisher_id=publisher_id,
        batch_size=settings.outbox_publisher_batch_size,
        claim_ttl=timedelta(seconds=settings.outbox_publisher_claim_seconds),
    )
    return OutboxPublisherRunner(
        publisher,
        transport,
        engine,
        publisher_id=publisher_id,
        stop_event=stop_event,
        poll_seconds=settings.outbox_publisher_poll_seconds,
        error_backoff_seconds=settings.outbox_publisher_error_backoff_seconds,
        max_error_backoff_seconds=settings.outbox_publisher_max_error_backoff_seconds,
    )


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    stop_event = Event()
    _install_signal_handlers(stop_event)
    build_runner(settings, stop_event).run()


if __name__ == "__main__":
    main()
