"""Observer behaviour of the simulation event bus (P17)."""

from datetime import UTC, datetime

from caudal_sim.event_bus import SimulationEvent, SimulationEventBus, SimulationEventKind

OCCURRED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)


class RecordingListener:
    """Test observer that keeps every event it receives, in arrival order."""

    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self.log = log
        self.events: list[SimulationEvent] = []

    def on_event(self, event: SimulationEvent) -> None:
        self.events.append(event)
        self.log.append(self.name)


def _event(detail: str) -> SimulationEvent:
    return SimulationEvent(
        occurred_at=OCCURRED_AT,
        kind=SimulationEventKind.VALVE_STATE_CHANGED,
        subject_id="valve-alto",
        detail=detail,
    )


def test_each_subscriber_receives_every_event_in_order() -> None:
    log: list[str] = []
    listener = RecordingListener("first", log)
    bus = SimulationEventBus()
    bus.subscribe(listener)

    bus.publish(_event("OPENING"))
    bus.publish(_event("OPEN"))

    assert [event.detail for event in listener.events] == ["OPENING", "OPEN"]


def test_listeners_are_notified_in_subscription_order() -> None:
    log: list[str] = []
    bus = SimulationEventBus()
    bus.subscribe(RecordingListener("first", log))
    bus.subscribe(RecordingListener("second", log))

    bus.publish(_event("CLOSED"))

    assert log == ["first", "second"]


def test_unsubscribed_listener_stops_receiving_events() -> None:
    log: list[str] = []
    listener = RecordingListener("only", log)
    bus = SimulationEventBus()
    bus.subscribe(listener)
    bus.publish(_event("OPENING"))

    bus.unsubscribe(listener)
    bus.publish(_event("OPEN"))

    assert [event.detail for event in listener.events] == ["OPENING"]


def test_unsubscribing_a_stranger_does_nothing() -> None:
    bus = SimulationEventBus()

    bus.unsubscribe(RecordingListener("stranger", []))
    bus.publish(_event("OPEN"))


def test_publishing_without_listeners_is_silent() -> None:
    SimulationEventBus().publish(_event("OPEN"))


def test_listener_can_unsubscribe_itself_during_delivery() -> None:
    class SelfRemovingListener(RecordingListener):
        def on_event(self, event: SimulationEvent) -> None:
            super().on_event(event)
            bus.unsubscribe(self)

    log: list[str] = []
    bus = SimulationEventBus()
    listener = SelfRemovingListener("once", log)
    bus.subscribe(listener)
    bus.subscribe(RecordingListener("after", log))

    bus.publish(_event("OPEN"))
    bus.publish(_event("CLOSED"))

    assert log == ["once", "after", "after"]
