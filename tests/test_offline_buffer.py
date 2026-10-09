"""Offline buffer proxy: queues while the network is down and sends in order (P11)."""

from typing import Literal

import pytest

from caudal_sim.offline_buffer import (
    BACKOFF_FACTOR,
    FIRST_BACKOFF_SECONDS,
    BufferFullError,
    OfflineBufferTransport,
)
from caudal_sim.telemetry_transport import (
    TelemetryRequest,
    TransportRejectedError,
    TransportUnavailableError,
    telemetry_request,
)

Outcome = Literal["ok", "down", "rejected"]
CAPACITY = 3
FIRST_POINT = {"id": "0190f3a2-6666-7000-8000-000000000001", "metric": "LEVEL", "value": 2.1}
SECOND_POINT = {"id": "0190f3a2-6666-7000-8000-000000000002", "metric": "LEVEL", "value": 2.0}
THIRD_POINT = {"id": "0190f3a2-6666-7000-8000-000000000003", "metric": "LEVEL", "value": 1.9}
MAX_ATTEMPTS = 3
QUEUED_BATCHES = 2


class ScriptedSubject:
    """Test subject: answers with the scripted outcomes, then 'ok'. Records delivered bodies."""

    def __init__(self, outcomes: list[Outcome]) -> None:
        self._outcomes = outcomes
        self.delivered: list[bytes] = []
        self.attempts = 0

    def send(self, request: TelemetryRequest) -> None:
        self.attempts += 1
        outcome: Outcome = self._outcomes.pop(0) if self._outcomes else "ok"
        if outcome == "down":
            raise TransportUnavailableError("sin red")
        if outcome == "rejected":
            raise TransportRejectedError(400, "VALIDATION_ERROR")
        self.delivered.append(request.body)


def _proxy(subject: ScriptedSubject, sleeps: list[float]) -> OfflineBufferTransport:
    return OfflineBufferTransport(subject, capacity=CAPACITY, sleeper=sleeps.append)


def _batch(point: dict[str, object]) -> TelemetryRequest:
    return telemetry_request([point])


def test_requests_pass_straight_through_when_the_network_is_up() -> None:
    subject = ScriptedSubject([])
    proxy = _proxy(subject, [])

    proxy.send(_batch(FIRST_POINT))

    assert subject.delivered == [_batch(FIRST_POINT).body]
    assert proxy.pending == 0


def test_batches_are_queued_while_down_and_sent_in_order_when_the_network_returns() -> None:
    subject = ScriptedSubject(["down", "down", "down"])
    proxy = _proxy(subject, [])
    proxy.send(_batch(FIRST_POINT))
    proxy.send(_batch(SECOND_POINT))
    proxy.send(_batch(THIRD_POINT))
    assert proxy.pending == CAPACITY

    delivered = proxy.flush()

    assert delivered == CAPACITY
    assert proxy.pending == 0
    assert subject.delivered == [
        _batch(FIRST_POINT).body,
        _batch(SECOND_POINT).body,
        _batch(THIRD_POINT).body,
    ]


def test_new_batch_waits_behind_older_ones_even_if_the_network_is_back() -> None:
    subject = ScriptedSubject(["down"])
    proxy = _proxy(subject, [])
    proxy.send(_batch(FIRST_POINT))

    proxy.send(_batch(SECOND_POINT))

    assert subject.delivered == [_batch(FIRST_POINT).body, _batch(SECOND_POINT).body]


def test_flush_stops_at_the_first_failure_and_keeps_the_rest_in_order() -> None:
    subject = ScriptedSubject(["down", "down", "down"])
    proxy = _proxy(subject, [])
    proxy.send(_batch(FIRST_POINT))
    proxy.send(_batch(SECOND_POINT))

    assert proxy.flush() == 0
    assert proxy.pending == QUEUED_BATCHES
    assert subject.delivered == []


def test_drain_waits_between_passes_and_then_empties_the_queue() -> None:
    subject = ScriptedSubject(["down", "down"])
    sleeps: list[float] = []
    proxy = _proxy(subject, sleeps)
    proxy.send(_batch(FIRST_POINT))

    delivered = proxy.drain(MAX_ATTEMPTS)

    assert delivered == 1
    assert proxy.pending == 0
    assert sleeps == [FIRST_BACKOFF_SECONDS]


def test_drain_gives_up_after_its_attempts_and_keeps_the_batches() -> None:
    # One failure for the first send, then one per drain pass: every pass fails.
    subject = ScriptedSubject(["down"] * (MAX_ATTEMPTS + 1))
    sleeps: list[float] = []
    proxy = _proxy(subject, sleeps)
    proxy.send(_batch(FIRST_POINT))

    delivered = proxy.drain(MAX_ATTEMPTS)

    assert delivered == 0
    assert proxy.pending == 1
    assert len(sleeps) == MAX_ATTEMPTS - 1
    assert sleeps[1] == pytest.approx(FIRST_BACKOFF_SECONDS * BACKOFF_FACTOR)


def test_full_buffer_refuses_new_batches_instead_of_dropping_data() -> None:
    subject = ScriptedSubject(["down"] * (CAPACITY + 1))
    proxy = _proxy(subject, [])
    for point in (FIRST_POINT, SECOND_POINT, THIRD_POINT):
        proxy.send(_batch(point))

    with pytest.raises(BufferFullError, match="lleno"):
        proxy.send(_batch(FIRST_POINT))
    assert proxy.pending == CAPACITY


def test_rejected_batch_is_removed_and_does_not_block_the_queue() -> None:
    subject = ScriptedSubject(["down", "rejected"])
    proxy = _proxy(subject, [])
    proxy.send(_batch(FIRST_POINT))
    proxy.send(_batch(SECOND_POINT))

    proxy.flush()

    assert proxy.rejected == 1
    assert proxy.pending == 0
    assert subject.delivered == [_batch(SECOND_POINT).body]


def test_buffer_needs_room_for_at_least_one_batch() -> None:
    with pytest.raises(ValueError, match="al menos un lote"):
        OfflineBufferTransport(ScriptedSubject([]), capacity=0, sleeper=lambda _s: None)
