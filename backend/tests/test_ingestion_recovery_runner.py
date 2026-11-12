from collections.abc import Iterable
from threading import Event

from backend.ingestion.recovery import RecoveryBatchResult
from backend.ingestion.recovery_runner import IngestionRecoveryRunner

EMPTY = RecoveryBatchResult(recovered=0, retries_scheduled=0, exhausted=0)


class FakeRecovery:
    def __init__(self, outcomes: Iterable[RecoveryBatchResult | BaseException], stop):
        self._outcomes = iter(outcomes)
        self._stop = stop
        self.calls = 0

    def recover_batch(self) -> RecoveryBatchResult:
        self.calls += 1
        try:
            outcome = next(self._outcomes)
        except StopIteration:
            self._stop.set()
            return EMPTY
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeEngine:
    def __init__(self):
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class RecordingEvent(Event):
    def __init__(self):
        super().__init__()
        self.waits = []

    def wait(self, timeout=None):
        if timeout is not None:
            self.waits.append(timeout)
        return super().wait(0)


def build_runner(outcomes):
    stop = RecordingEvent()
    recovery = FakeRecovery(outcomes, stop)
    engine = FakeEngine()
    runner = IngestionRecoveryRunner(
        recovery,
        engine,
        stop_event=stop,
        poll_seconds=5,
        error_backoff_seconds=2,
        max_error_backoff_seconds=5,
    )
    return runner, recovery, engine, stop


def test_runner_drains_recovered_work_then_polls():
    recovered = RecoveryBatchResult(recovered=2, retries_scheduled=2, exhausted=0)
    runner, recovery, engine, stop = build_runner([recovered, EMPTY])

    runner.run()

    assert recovery.calls == 3
    assert stop.waits == [5]
    assert engine.disposed is True


def test_runner_uses_capped_backoff_for_database_failures():
    runner, recovery, engine, stop = build_runner(
        [RuntimeError("db"), RuntimeError("db"), RuntimeError("db")]
    )

    runner.run()

    assert recovery.calls == 4
    assert stop.waits == [2, 4, 5]
    assert engine.disposed is True
