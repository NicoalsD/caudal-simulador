"""Event bus of the simulation: components announce what happened, observers react.

Commands, valves and the step loop publish events here, so that the dashboard, the log and
the tests can follow the simulation without the publishers knowing who listens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class SimulationEventKind(StrEnum):
    """Kinds of event the simulated devices publish."""

    VALVE_STATE_CHANGED = "VALVE_STATE_CHANGED"
    COMMAND_DELIVERED = "COMMAND_DELIVERED"
    COMMAND_CONFIRMED = "COMMAND_CONFIRMED"


@dataclass(frozen=True)
class SimulationEvent:
    """Something that happened at an instant: a kind, the subject it concerns and a detail."""

    occurred_at: datetime
    kind: SimulationEventKind
    subject_id: str
    detail: str


class EventListener(Protocol):
    """Observer interface: receives every event published after it subscribed."""

    def on_event(self, event: SimulationEvent) -> None:
        """Reacts to one event."""


class SimulationEventBus:
    """Synchronous publisher: each listener receives each event, in subscription order.

    @pattern P17 Observer
    """

    def __init__(self) -> None:
        self._listeners: list[EventListener] = []

    def subscribe(self, listener: EventListener) -> None:
        """Adds a listener. Subscribing the same object twice delivers each event twice."""
        self._listeners.append(listener)

    def unsubscribe(self, listener: EventListener) -> None:
        """Removes a listener. Removing one that is not subscribed does nothing."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def publish(self, event: SimulationEvent) -> None:
        """Delivers `event` to every current listener."""
        for listener in tuple(self._listeners):
            listener.on_event(event)
