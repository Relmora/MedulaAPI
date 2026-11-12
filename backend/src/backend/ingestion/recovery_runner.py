"""Command-line loop that recovers expired ingestion leases."""

import signal
from threading import Event
from types import FrameType
from typing import Protocol

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.database import create_database_engine
from backend.ingestion.recovery import IngestionLeaseRecovery, RecoveryBatchResult
from backend.logging import configure_logging, get_logger

logger = get_logger(__name__)


class BatchRecovery(Protocol):
    def recover_batch(self) -> RecoveryBatchResult: ...


class DisposableEngine(Protocol):
    def dispose(self) -> None: ...


class IngestionRecoveryRunner:
    """Recover expired leases until shutdown, with bounded database backoff."""

    def __init__(
        self,
        recovery: BatchRecovery,
        engine: DisposableEngine,
        *,
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
        self._recovery = recovery
        self._engine = engine
        self._stop_event = stop_event
        self._poll_seconds = poll_seconds
        self._error_backoff_seconds = error_backoff_seconds
        self._max_error_backoff_seconds = max_error_backoff_seconds

    def run(self) -> None:
        consecutive_failures = 0
        logger.info(
            "Ingestion lease recovery started",
            extra={"event": "ingestion.recovery.started"},
        )
        try:
            while not self._stop_event.is_set():
                try:
                    result = self._recovery.recover_batch()
                except Exception:
                    consecutive_failures += 1
                    retry_seconds = min(
                        self._error_backoff_seconds * (2 ** (consecutive_failures - 1)),
                        self._max_error_backoff_seconds,
                    )
                    logger.exception(
                        "Ingestion lease recovery batch failed",
                        extra={
                            "event": "ingestion.recovery.batch_failed",
                            "failure_count": consecutive_failures,
                            "retry_seconds": retry_seconds,
                        },
                    )
                    self._stop_event.wait(retry_seconds)
                    continue

                consecutive_failures = 0
                if result.recovered:
                    logger.warning(
                        "Expired ingestion leases recovered",
                        extra={
                            "event": "ingestion.recovery.batch_completed",
                            "recovered": result.recovered,
                            "retries_scheduled": result.retries_scheduled,
                            "exhausted": result.exhausted,
                        },
                    )
                if result.recovered == 0 and not self._stop_event.is_set():
                    self._stop_event.wait(self._poll_seconds)
        finally:
            try:
                self._engine.dispose()
            except Exception:
                logger.exception(
                    "Ingestion recovery database cleanup failed",
                    extra={"event": "ingestion.recovery.cleanup_failed"},
                )
            logger.info(
                "Ingestion lease recovery stopped",
                extra={"event": "ingestion.recovery.stopped"},
            )


def _install_signal_handlers(stop_event: Event) -> None:
    def request_shutdown(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


def build_runner(settings: Settings, stop_event: Event) -> IngestionRecoveryRunner:
    engine: Engine = create_database_engine(settings)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    recovery = IngestionLeaseRecovery(
        sessions,
        batch_size=settings.ingestion_recovery_batch_size,
    )
    return IngestionRecoveryRunner(
        recovery,
        engine,
        stop_event=stop_event,
        poll_seconds=settings.ingestion_recovery_poll_seconds,
        error_backoff_seconds=settings.ingestion_recovery_error_backoff_seconds,
        max_error_backoff_seconds=(
            settings.ingestion_recovery_max_error_backoff_seconds
        ),
    )


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    stop_event = Event()
    _install_signal_handlers(stop_event)
    build_runner(settings, stop_event).run()


if __name__ == "__main__":
    main()
