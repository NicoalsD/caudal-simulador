"""Offline buffer of telemetry: keeps the batches that did not arrive and sends them in order.

The proxy stands in front of the real transport. When the network is up, requests pass
straight through. When it is down, requests wait in a FIFO queue and are sent, oldest first,
as soon as the network answers again. A batch is never sent before an older one, and the
queue stops at the first network failure, so the API receives the points in the order they
were measured. Points keep their identifiers, so a batch sent twice is a duplicate, not a
new reading.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from caudal_sim.telemetry_transport import (
    TelemetryRequest,
    TelemetryTransport,
    TransportRejectedError,
    TransportUnavailableError,
)

BACKOFF_FACTOR = 2.0
FIRST_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 300.0


class BufferFullError(Exception):
    """The offline buffer has no room. Nothing is dropped silently."""

    def __init__(self, capacity: int) -> None:
        message = f"El buffer sin conexión está lleno (capacidad {capacity} lotes)."
        super().__init__(message)
        self.capacity = capacity


class OfflineBufferTransport:
    """Proxy of a `TelemetryTransport` that queues the batches it cannot send.

    `drain` retries with exponential backoff. The sleeper is injected, so tests never wait.

    @pattern P11 Proxy
    """

    def __init__(
        self,
        subject: TelemetryTransport,
        *,
        capacity: int,
        sleeper: Callable[[float], None],
    ) -> None:
        if capacity < 1:
            raise ValueError("la capacidad del buffer debe ser de al menos un lote")
        self._subject = subject
        self._capacity = capacity
        self._sleeper = sleeper
        self._queue: deque[TelemetryRequest] = deque()
        self._rejected = 0

    @property
    def pending(self) -> int:
        """Batches waiting for the network."""
        return len(self._queue)

    @property
    def rejected(self) -> int:
        """Batches the API refused for good and that were removed from the queue."""
        return self._rejected

    def send(self, request: TelemetryRequest) -> None:
        """Sends now if nothing is waiting; otherwise queues it behind the waiting batches."""
        if self._queue:
            self._enqueue(request)
            self.flush()
            return
        try:
            self._subject.send(request)
        except TransportUnavailableError:
            self._enqueue(request)

    def flush(self) -> int:
        """Sends the queued batches in order, one pass. Returns how many were delivered."""
        delivered = 0
        while self._queue:
            try:
                self._subject.send(self._queue[0])
            except TransportUnavailableError:
                break
            except TransportRejectedError:
                self._queue.popleft()
                self._rejected += 1
                continue
            self._queue.popleft()
            delivered += 1
        return delivered

    def drain(self, max_attempts: int) -> int:
        """Flushes until the queue is empty or `max_attempts` passes have been made.

        Between two passes it waits with exponential backoff. Returns how many were delivered.
        """
        if max_attempts < 1:
            raise ValueError("drain necesita al menos un intento")
        delivered = 0
        delay = FIRST_BACKOFF_SECONDS
        for attempt in range(1, max_attempts + 1):
            delivered += self.flush()
            if not self._queue:
                break
            if attempt < max_attempts:
                self._sleeper(delay)
                delay = min(delay * BACKOFF_FACTOR, MAX_BACKOFF_SECONDS)
        return delivered

    def _enqueue(self, request: TelemetryRequest) -> None:
        if len(self._queue) >= self._capacity:
            raise BufferFullError(self._capacity)
        self._queue.append(request)
