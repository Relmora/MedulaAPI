"""Renew worker leases while an ingestion pipeline is still active."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Iterator

from sqlalchemy import select

from backend.ingestion.claim import ClaimedIngestionJob, Clock, SessionFactory
from backend.logging import get_logger
from backend.models import IngestionJob, IngestionJobAttempt

logger = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IngestionLeaseHeartbeat:
    """Keep durable ownership alive until pipeline processing finishes."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        lease_ttl: timedelta,
        interval: timedelta | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        interval = interval or lease_ttl / 3
        if interval <= timedelta(0) or interval >= lease_ttl:
            raise ValueError("interval must be positive and shorter than lease_ttl")
        self._session_factory = session_factory
        self._lease_ttl = lease_ttl
        self._interval_seconds = interval.total_seconds()
        self._clock = clock

    def renew(self, claimed: ClaimedIngestionJob) -> bool:
        """Extend a lease only while this exact worker attempt still owns it."""
        now = self._aware_now()
        lease_expires_at = now + self._lease_ttl
        with self._session_factory() as db, db.begin():
            job = db.scalar(
                select(IngestionJob)
                .where(IngestionJob.id == claimed.job_id)
                .with_for_update()
            )
            attempt = db.scalar(
                select(IngestionJobAttempt)
                .where(IngestionJobAttempt.id == claimed.attempt_id)
                .with_for_update()
            )
            if (
                job is None
                or attempt is None
                or job.status != "PROCESSING"
                or attempt.status != "RUNNING"
                or job.claimed_by != claimed.worker_id
                or attempt.worker_id != claimed.worker_id
                or attempt.job_id != job.id
            ):
                return False
            job.lease_expires_at = lease_expires_at
            job.updated_at = now
            attempt.heartbeat_at = now
            attempt.lease_expires_at = lease_expires_at
            return True

    @contextmanager
    def maintain(self, claimed: ClaimedIngestionJob) -> Iterator[None]:
        """Renew in the background until the surrounding pipeline exits."""
        stopped = Event()
        thread = Thread(
            target=self._run,
            args=(claimed, stopped),
            name=f"ingestion-lease-{claimed.attempt_id}",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join()

    def _run(self, claimed: ClaimedIngestionJob, stopped: Event) -> None:
        while not stopped.wait(self._interval_seconds):
            try:
                if not self.renew(claimed):
                    logger.warning(
                        "Ingestion lease ownership was lost",
                        extra={
                            "event": "ingestion.lease.lost",
                            "job_id": str(claimed.job_id),
                            "attempt_id": str(claimed.attempt_id),
                            "worker_id": claimed.worker_id,
                        },
                    )
                    return
            except Exception:
                logger.exception(
                    "Ingestion lease renewal failed",
                    extra={
                        "event": "ingestion.lease.renewal_failed",
                        "job_id": str(claimed.job_id),
                        "attempt_id": str(claimed.attempt_id),
                        "worker_id": claimed.worker_id,
                    },
                )

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now
