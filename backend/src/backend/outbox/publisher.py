"""Claim and publish transactional outbox events without holding DB locks."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from backend.models import OutboxEvent

DEFAULT_CLAIM_TTL = timedelta(seconds=30)
DEFAULT_BATCH_SIZE = 50
MAX_RECORDED_ERROR_LENGTH = 4000
MAX_PUBLISHER_ID_LENGTH = 200

SessionFactory = Callable[[], Session]
Clock = Callable[[], datetime]
RetryDelay = Callable[[int], timedelta]


@dataclass(frozen=True)
class OutboxMessage:
    """Stable broker message assembled from a claimed outbox row."""

    event_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    schema_version: int
    occurred_at: datetime
    data: Mapping[str, object]

    def envelope(self) -> dict[str, object]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": str(self.aggregate_id),
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at.isoformat(),
            "data": dict(self.data),
        }


class ConfirmingEventTransport(Protocol):
    """Broker adapter that returns only after the broker confirms a message."""

    def publish(self, message: OutboxMessage) -> None: ...


@dataclass(frozen=True)
class PublishBatchResult:
    claimed: int
    published: int
    failed: int
    lost_claims: int


@dataclass(frozen=True)
class _ClaimedEvent:
    message: OutboxMessage
    claim_token: str
    publish_attempt: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _exponential_retry_delay(attempt_number: int) -> timedelta:
    """Return a capped retry delay; jitter can be added by a broker adapter later."""
    if attempt_number <= 0:
        raise ValueError("attempt_number must be positive")
    seconds = min(5 * (2 ** (attempt_number - 1)), 300)
    return timedelta(seconds=seconds)


class OutboxPublisher:
    """Publish one leased batch of due events using at-least-once delivery."""

    def __init__(
        self,
        session_factory: SessionFactory,
        transport: ConfirmingEventTransport,
        *,
        publisher_id: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        claim_ttl: timedelta = DEFAULT_CLAIM_TTL,
        clock: Clock = _utc_now,
        retry_delay: RetryDelay = _exponential_retry_delay,
    ) -> None:
        normalized_publisher_id = publisher_id.strip()
        if not normalized_publisher_id:
            raise ValueError("publisher_id must be nonempty")
        if len(normalized_publisher_id) > MAX_PUBLISHER_ID_LENGTH:
            raise ValueError(
                f"publisher_id must not exceed {MAX_PUBLISHER_ID_LENGTH} characters"
            )
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if claim_ttl <= timedelta(0):
            raise ValueError("claim_ttl must be positive")

        self._session_factory = session_factory
        self._transport = transport
        self._publisher_id = normalized_publisher_id
        self._batch_size = batch_size
        self._claim_ttl = claim_ttl
        self._clock = clock
        self._retry_delay = retry_delay

    def publish_batch(self) -> PublishBatchResult:
        """Claim a batch, publish each event, and persist each outcome."""
        claimed_events = self._claim_batch()
        published = 0
        failed = 0
        lost_claims = 0

        for claimed in claimed_events:
            try:
                self._transport.publish(claimed.message)
            except Exception as error:
                failed += 1
                if not self._schedule_retry(claimed, error):
                    lost_claims += 1
            else:
                if self._mark_published(claimed):
                    published += 1
                else:
                    lost_claims += 1

        return PublishBatchResult(
            claimed=len(claimed_events),
            published=published,
            failed=failed,
            lost_claims=lost_claims,
        )

    def _claim_batch(self) -> list[_ClaimedEvent]:
        claimed_events: list[_ClaimedEvent] = []
        now = self._aware_now()

        with self._session_factory() as db, db.begin():
            statement = (
                select(OutboxEvent)
                .where(
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.available_at <= now,
                    or_(
                        OutboxEvent.claimed_by.is_(None),
                        OutboxEvent.claim_expires_at.is_(None),
                        OutboxEvent.claim_expires_at <= now,
                    ),
                )
                .order_by(
                    OutboxEvent.available_at,
                    OutboxEvent.created_at,
                    OutboxEvent.id,
                )
                .limit(self._batch_size)
                .with_for_update(skip_locked=True)
            )
            events = list(db.scalars(statement))

            for event in events:
                claim_token = f"{self._publisher_id}:{uuid4()}"
                event.claimed_by = claim_token
                event.claim_expires_at = now + self._claim_ttl
                event.publish_attempts += 1
                event.last_error = None
                claimed_events.append(
                    _ClaimedEvent(
                        message=OutboxMessage(
                            event_id=event.id,
                            event_type=event.event_type,
                            aggregate_type=event.aggregate_type,
                            aggregate_id=event.aggregate_id,
                            schema_version=event.schema_version,
                            occurred_at=event.created_at,
                            data=dict(event.payload),
                        ),
                        claim_token=claim_token,
                        publish_attempt=event.publish_attempts,
                    )
                )

        return claimed_events

    def _mark_published(self, claimed: _ClaimedEvent) -> bool:
        now = self._aware_now()
        with self._session_factory() as db, db.begin():
            updated_event_id = db.scalar(
                update(OutboxEvent)
                .where(
                    OutboxEvent.id == claimed.message.event_id,
                    OutboxEvent.claimed_by == claimed.claim_token,
                    OutboxEvent.published_at.is_(None),
                )
                .values(
                    published_at=now,
                    claimed_by=None,
                    claim_expires_at=None,
                    last_error=None,
                )
                .returning(OutboxEvent.id)
            )
            return updated_event_id is not None

    def _schedule_retry(self, claimed: _ClaimedEvent, error: Exception) -> bool:
        now = self._aware_now()
        retry_at = now + self._retry_delay(claimed.publish_attempt)
        error_text = f"{type(error).__name__}: {error}"[:MAX_RECORDED_ERROR_LENGTH]

        with self._session_factory() as db, db.begin():
            updated_event_id = db.scalar(
                update(OutboxEvent)
                .where(
                    OutboxEvent.id == claimed.message.event_id,
                    OutboxEvent.claimed_by == claimed.claim_token,
                    OutboxEvent.published_at.is_(None),
                )
                .values(
                    available_at=retry_at,
                    claimed_by=None,
                    claim_expires_at=None,
                    last_error=error_text,
                )
                .returning(OutboxEvent.id)
            )
            return updated_event_id is not None

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now
