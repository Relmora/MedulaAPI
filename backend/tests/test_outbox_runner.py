import logging
from collections.abc import Iterable
from threading import Event

import pytest

from backend.outbox.publisher import PublishBatchResult
from backend.outbox.runner import OutboxPublisherRunner, create_publisher_id

EMPTY_BATCH = PublishBatchResult(
    claimed=0,
    published=0,
    failed=0,
    lost_claims=0,
)


class FakePublisher:
    def __init__(
        self,
        outcomes: Iterable[PublishBatchResult | BaseException],
        stop_event: Event,
    ) -> None:
        self._outcomes = iter(outcomes)
        self._stop_event = stop_event
        self.calls = 0

    def publish_batch(self) -> PublishBatchResult:
        self.calls += 1
        try:
            outcome = next(self._outcomes)
        except StopIteration:
            self._stop_event.set()
            return EMPTY_BATCH
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeTransport:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class RecordingEvent(Event):
    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float] = []

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is not None:
            self.waits.append(timeout)
        return super().wait(0)


def runner(
    outcomes: Iterable[PublishBatchResult | BaseException],
) -> tuple[
    OutboxPublisherRunner, FakePublisher, FakeTransport, FakeEngine, RecordingEvent
]:
    stop_event = RecordingEvent()
    publisher = FakePublisher(outcomes, stop_event)
    transport = FakeTransport()
    engine = FakeEngine()
    instance = OutboxPublisherRunner(
        publisher,
        transport,
        engine,
        publisher_id="test-publisher",
        stop_event=stop_event,
        poll_seconds=1,
        error_backoff_seconds=2,
        max_error_backoff_seconds=5,
    )
    return instance, publisher, transport, engine, stop_event


def test_runner_publishes_batches_and_cleans_up(caplog):
    successful = PublishBatchResult(
        claimed=2,
        published=2,
        failed=0,
        lost_claims=0,
    )
    instance, publisher, transport, engine, stop_event = runner(
        [successful, EMPTY_BATCH]
    )

    with caplog.at_level(logging.INFO, logger="backend.outbox.runner"):
        instance.run()

    assert publisher.calls == 3
    assert stop_event.waits == [1]
    assert transport.closed is True
    assert engine.disposed is True
    assert "Outbox publisher started" in caplog.messages
    assert "Outbox publisher batch completed" in caplog.messages
    assert "Outbox publisher stopped" in caplog.messages


def test_runner_uses_capped_backoff_for_database_failures(caplog):
    instance, publisher, transport, engine, stop_event = runner(
        [
            RuntimeError("database unavailable"),
            RuntimeError("database unavailable"),
            RuntimeError("database unavailable"),
        ]
    )

    with caplog.at_level(logging.ERROR, logger="backend.outbox.runner"):
        instance.run()

    assert publisher.calls == 4
    assert stop_event.waits == [2, 4, 5]
    assert transport.closed is True
    assert engine.disposed is True
    assert caplog.messages.count("Outbox publisher batch failed") == 3


def test_success_resets_infrastructure_failure_backoff():
    successful = PublishBatchResult(
        claimed=1,
        published=1,
        failed=0,
        lost_claims=0,
    )
    instance, _, _, _, stop_event = runner(
        [
            RuntimeError("database unavailable"),
            successful,
            RuntimeError("database unavailable"),
        ]
    )

    instance.run()

    assert stop_event.waits == [2, 2]


def test_cleanup_runs_when_loop_is_interrupted():
    instance, publisher, transport, engine, _ = runner([KeyboardInterrupt()])

    with pytest.raises(KeyboardInterrupt):
        instance.run()

    assert publisher.calls == 1
    assert transport.closed is True
    assert engine.disposed is True


def test_invalid_runner_timing_is_rejected():
    stop_event = Event()
    with pytest.raises(ValueError, match="poll_seconds"):
        OutboxPublisherRunner(
            FakePublisher([], stop_event),
            FakeTransport(),
            FakeEngine(),
            publisher_id="publisher",
            stop_event=stop_event,
            poll_seconds=0,
            error_backoff_seconds=1,
            max_error_backoff_seconds=2,
        )
    with pytest.raises(ValueError, match="at least"):
        OutboxPublisherRunner(
            FakePublisher([], stop_event),
            FakeTransport(),
            FakeEngine(),
            publisher_id="publisher",
            stop_event=stop_event,
            poll_seconds=1,
            error_backoff_seconds=3,
            max_error_backoff_seconds=2,
        )


def test_publisher_identity_is_unique_and_bounded():
    first = create_publisher_id()
    second = create_publisher_id()

    assert first != second
    assert len(first) <= 200
