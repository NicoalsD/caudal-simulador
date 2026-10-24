"""SSE of the dashboard: framing, ordering, bounded queue and clean unsubscription."""

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from caudal_sim.dashboard_api import EVENTS_PATH, create_dashboard_app
from caudal_sim.dashboard_events import (
    DROPPED_EVENT_NAME,
    EventStreamListener,
    event_frame,
    format_sse,
    stream_frames,
)
from caudal_sim.dashboard_session import DashboardSession
from caudal_sim.event_bus import SimulationEvent, SimulationEventBus, SimulationEventKind

AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
VALVE_ID = "0190f3a2-7000-7000-8000-000000000001"
OPEN_DETAIL = "OPEN"
CLOSE_DETAIL = "CLOSED"
BUFFER_CAPACITY = 2
THREE_EVENTS = 3
PUBLISH_PAUSE_SECONDS = 0.01
HTTP_OK = 200


def _valve_event(detail: str) -> SimulationEvent:
    return SimulationEvent(
        occurred_at=AT,
        kind=SimulationEventKind.VALVE_STATE_CHANGED,
        subject_id=VALVE_ID,
        detail=detail,
    )


async def _never_disconnected() -> bool:
    return False


async def _collect(
    bus: SimulationEventBus, *, max_events: int | None, capacity: int = 256
) -> list[str]:
    frames: list[str] = []
    async for frame in stream_frames(
        bus,
        is_disconnected=_never_disconnected,
        max_events=max_events,
        capacity=capacity,
        heartbeat_seconds=0.01,
    ):
        frames.append(frame)
    return frames


def test_frame_has_id_name_and_one_line_of_data() -> None:
    frame = format_sse("VALVE_STATE_CHANGED", '{"a":1}', event_id=7)

    assert frame == 'id: 7\nevent: VALVE_STATE_CHANGED\ndata: {"a":1}\n\n'


def test_event_frame_names_the_frame_after_its_kind() -> None:
    frame = event_frame(3, _valve_event(OPEN_DETAIL))

    lines = frame.splitlines()
    assert lines[:2] == ["id: 3", "event: VALVE_STATE_CHANGED"]
    assert lines[2].startswith("data: {")
    assert '"detail":"OPEN"' in lines[2]
    assert frame.endswith("\n\n")


def test_events_arrive_in_the_order_they_were_published() -> None:
    bus = SimulationEventBus()

    async def run() -> list[str]:
        task = asyncio.create_task(_collect(bus, max_events=2))
        await asyncio.sleep(0)
        bus.publish(_valve_event(OPEN_DETAIL))
        bus.publish(_valve_event(CLOSE_DETAIL))
        return await task

    frames = asyncio.run(run())

    assert [frame.split("\n")[0] for frame in frames] == ["id: 1", "id: 2"]
    assert '"detail":"OPEN"' in frames[0]
    assert '"detail":"CLOSED"' in frames[1]


def test_events_published_from_another_thread_reach_the_stream() -> None:
    bus = SimulationEventBus()

    async def run() -> list[str]:
        task = asyncio.create_task(_collect(bus, max_events=1))
        await asyncio.sleep(0)
        worker = threading.Thread(target=bus.publish, args=(_valve_event(OPEN_DETAIL),))
        worker.start()
        worker.join()
        return await task

    frames = asyncio.run(run())

    assert len(frames) == 1
    assert "event: VALVE_STATE_CHANGED" in frames[0]


def test_a_full_queue_counts_the_lost_events_and_reports_them() -> None:
    bus = SimulationEventBus()

    async def run() -> list[str]:
        task = asyncio.create_task(_collect(bus, max_events=2, capacity=BUFFER_CAPACITY))
        await asyncio.sleep(0)
        for _ in range(THREE_EVENTS):
            bus.publish(_valve_event(OPEN_DETAIL))
        return await task

    frames = asyncio.run(run())

    dropped = [frame for frame in frames if f"event: {DROPPED_EVENT_NAME}" in frame]
    assert len(dropped) == 1
    assert '"dropped":1' in dropped[0]


def test_stream_unsubscribes_when_it_ends() -> None:
    bus = SimulationEventBus()

    async def run() -> None:
        task = asyncio.create_task(_collect(bus, max_events=1))
        await asyncio.sleep(0)
        bus.publish(_valve_event(OPEN_DETAIL))
        await task

    asyncio.run(run())

    assert bus._listeners == []


def test_listener_queues_an_event_handed_over_by_the_bus() -> None:
    async def run() -> int:
        loop = asyncio.get_running_loop()
        listener = EventStreamListener(loop, capacity=BUFFER_CAPACITY)
        listener.on_event(_valve_event(OPEN_DETAIL))
        await asyncio.sleep(0)
        received = await listener.next_event(timeout=1.0)
        assert received is not None
        return received[0]

    assert asyncio.run(run()) == 1


def test_endpoint_streams_valve_events_and_closes_after_max_events() -> None:
    session = DashboardSession(scenario="normal-year")
    client = TestClient(create_dashboard_app(session))
    stop = threading.Event()

    def publish_until_stopped(publish: Callable[[SimulationEvent], Any]) -> None:
        while not stop.is_set():
            publish(_valve_event(OPEN_DETAIL))
            stop.wait(PUBLISH_PAUSE_SECONDS)

    worker = threading.Thread(target=publish_until_stopped, args=(session.bus.publish,))
    worker.start()
    try:
        response = client.get(EVENTS_PATH, params={"max_events": 1})
    finally:
        stop.set()
        worker.join()

    assert response.status_code == HTTP_OK
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: VALVE_STATE_CHANGED" in response.text
