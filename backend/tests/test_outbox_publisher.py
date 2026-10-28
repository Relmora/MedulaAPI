from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base, OutboxEvent
from backend.outbox import OutboxMessage, OutboxPublisher


class RecordingTransport:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.messages: list[OutboxMessage] = []

    def publish(self, message: OutboxMessage) -> None:
        self.messages.append(message)
        if self.error is not None:
            raise self.error


@pytest.fixture
def outbox_database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def add_event(factory, *, available_at: datetime, **values) -> OutboxEvent:
    event = OutboxEvent(
        event_type="INGESTION_JOB_REQUESTED",
        aggregate_type="INGESTION_JOB",
        aggregate_id=uuid4(),
        schema_version=1,
        payload={"job_id": str(uuid4())},
        available_at=available_at,
        **values,
    )
    with factory() as db:
        db.add(event)
        db.commit()
    return event


def test_publish_batch_claims_and_marks_confirmed_event(outbox_database):
    now = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
    event = add_event(outbox_database, available_at=now)
    transport = RecordingTransport()
    publisher = OutboxPublisher(
        outbox_database,
        transport,
        publisher_id="publisher-1",
        clock=lambda: now,
    )

    result = publisher.publish_batch()

    assert result.claimed == 1
    assert result.published == 1
    assert result.failed == 0
    assert result.lost_claims == 0
    assert len(transport.messages) == 1
    assert transport.messages[0].event_id == event.id
    assert transport.messages[0].envelope()["event_id"] == str(event.id)
    with outbox_database() as db:
        saved = db.get(OutboxEvent, event.id)
        assert saved.published_at.replace(tzinfo=UTC) == now
        assert saved.publish_attempts == 1
        assert saved.claimed_by is None
        assert saved.claim_expires_at is None
        assert saved.last_error is None


def test_publish_failure_releases_claim_and_schedules_retry(outbox_database):
    now = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
    event = add_event(outbox_database, available_at=now)
    transport = RecordingTransport(ConnectionError("RabbitMQ unavailable"))
    publisher = OutboxPublisher(
        outbox_database,
        transport,
        publisher_id="publisher-1",
        clock=lambda: now,
        retry_delay=lambda attempt: timedelta(seconds=attempt * 10),
    )

    result = publisher.publish_batch()

    assert result.claimed == 1
    assert result.published == 0
    assert result.failed == 1
    assert result.lost_claims == 0
    with outbox_database() as db:
        saved = db.get(OutboxEvent, event.id)
        assert saved.published_at is None
        assert saved.publish_attempts == 1
        assert saved.available_at.replace(tzinfo=UTC) == now + timedelta(seconds=10)
        assert saved.claimed_by is None
        assert saved.claim_expires_at is None
        assert saved.last_error == "ConnectionError: RabbitMQ unavailable"


def test_active_claim_is_skipped_and_expired_claim_is_recovered(outbox_database):
    now = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
    active = add_event(
        outbox_database,
        available_at=now,
        claimed_by="another-publisher",
        claim_expires_at=now + timedelta(seconds=1),
    )
    expired = add_event(
        outbox_database,
        available_at=now,
        claimed_by="crashed-publisher",
        claim_expires_at=now - timedelta(seconds=1),
    )
    transport = RecordingTransport()
    publisher = OutboxPublisher(
        outbox_database,
        transport,
        publisher_id="publisher-1",
        clock=lambda: now,
    )

    result = publisher.publish_batch()

    assert result.claimed == 1
    assert transport.messages[0].event_id == expired.id
    with outbox_database() as db:
        assert db.get(OutboxEvent, active.id).published_at is None
        assert db.get(OutboxEvent, expired.id).published_at is not None


def test_future_and_already_published_events_are_skipped(outbox_database):
    now = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
    add_event(outbox_database, available_at=now + timedelta(seconds=1))
    add_event(outbox_database, available_at=now, published_at=now)
    transport = RecordingTransport()
    publisher = OutboxPublisher(
        outbox_database,
        transport,
        publisher_id="publisher-1",
        clock=lambda: now,
    )

    result = publisher.publish_batch()

    assert result == result.__class__(claimed=0, published=0, failed=0, lost_claims=0)
    assert transport.messages == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"publisher_id": " "}, "publisher_id must be nonempty"),
        ({"publisher_id": "publisher", "batch_size": 0}, "batch_size"),
        (
            {"publisher_id": "publisher", "claim_ttl": timedelta(0)},
            "claim_ttl",
        ),
    ],
)
def test_invalid_publisher_configuration_is_rejected(outbox_database, kwargs, message):
    with pytest.raises(ValueError, match=message):
        OutboxPublisher(outbox_database, RecordingTransport(), **kwargs)


def test_clock_must_be_timezone_aware(outbox_database):
    publisher = OutboxPublisher(
        outbox_database,
        RecordingTransport(),
        publisher_id="publisher-1",
        clock=lambda: datetime(2026, 10, 29),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        publisher.publish_batch()
