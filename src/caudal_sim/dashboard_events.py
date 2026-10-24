"""Server-sent events (SSE) of the dashboard: simulation events streamed to the browser.

The event bus is synchronous and may publish from the simulation thread. The listener hands
each event to the event loop of the API with `call_soon_threadsafe`, through a bounded queue.
A client that falls behind does not slow the simulation: the events that do not fit are
counted and reported with a `DROPPED` frame, so the gap is visible in the dashboard.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime

from pydantic import BaseModel, Field

from caudal_sim.event_bus import SimulationEvent, SimulationEventBus

SSE_CONTENT_TYPE = "text/event-stream"
DEFAULT_QUEUE_CAPACITY = 256
DEFAULT_HEARTBEAT_SECONDS = 15.0
DROPPED_EVENT_NAME = "DROPPED"
HEARTBEAT_FRAME = ": latido\n\n"
MAX_STREAM_EVENTS = 10_000


class SimulationEventOut(BaseModel):
    """One simulation event as the dashboard receives it."""

    occurred_at: datetime = Field(description="Instante simulado en que ocurrió el evento.")
    kind: str = Field(description="Tipo de evento; también es el nombre del evento SSE.")
    subject_id: str = Field(description="Identificador del elemento afectado (válvula, comando).")
    detail: str = Field(description="Detalle del evento, por ejemplo el nuevo estado.")


class EventStreamListener:
    """Observer that queues the events for one SSE client, in the order the bus delivers them.

    `on_event` may run in any thread. The queue lives in the event loop, which only it touches.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, capacity: int) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[tuple[int, SimulationEvent]] = asyncio.Queue(maxsize=capacity)
        self._sequence = 0
        self._dropped = 0

    def on_event(self, event: SimulationEvent) -> None:
        """Observer hook. Safe to call from the simulation thread."""
        self._loop.call_soon_threadsafe(self._offer, event)

    def _offer(self, event: SimulationEvent) -> None:
        if self._queue.full():
            self._dropped += 1
            return
        self._sequence += 1
        self._queue.put_nowait((self._sequence, event))

    def take_dropped(self) -> int:
        """Events lost since the last call, because the queue was full."""
        dropped, self._dropped = self._dropped, 0
        return dropped

    async def next_event(self, timeout: float) -> tuple[int, SimulationEvent] | None:
        """Next queued event, or None when nothing arrives within `timeout` seconds."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None


def format_sse(event_name: str, data: str, event_id: int | None = None) -> str:
    """One SSE frame. `data` must be a single line, which the JSON encoder guarantees."""
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_name}")
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


def event_frame(sequence: int, event: SimulationEvent) -> str:
    """The SSE frame of one simulation event, with the event kind as its name."""
    payload = SimulationEventOut(
        occurred_at=event.occurred_at,
        kind=str(event.kind),
        subject_id=event.subject_id,
        detail=event.detail,
    )
    return format_sse(str(event.kind), payload.model_dump_json(), event_id=sequence)


async def stream_frames(
    bus: SimulationEventBus,
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
    max_events: int | None = None,
    capacity: int = DEFAULT_QUEUE_CAPACITY,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """Yields the SSE frames of the bus until the client leaves or `max_events` are sent.

    The listener is subscribed while the generator runs and removed when it ends, even when
    the client disconnects in the middle of a frame.
    """
    loop = asyncio.get_running_loop()
    listener = EventStreamListener(loop, capacity)
    bus.subscribe(listener)
    sent = 0
    try:
        while max_events is None or sent < max_events:
            if await is_disconnected():
                break
            dropped = listener.take_dropped()
            if dropped:
                yield format_sse(DROPPED_EVENT_NAME, f'{{"dropped":{dropped}}}')
            received = await listener.next_event(heartbeat_seconds)
            if received is None:
                yield HEARTBEAT_FRAME
                continue
            sequence, event = received
            sent += 1
            yield event_frame(sequence, event)
    finally:
        bus.unsubscribe(listener)
