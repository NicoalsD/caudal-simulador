"""Ordered schedule of the simulation events of a day.

The schedule sorts the events once by instant. Events with the same instant keep the order
in which they were written, so a run always replays the same sequence.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Self

from caudal_sim.event_bus import SimulationEvent


def _sorted_events(events: Iterable[SimulationEvent]) -> tuple[SimulationEvent, ...]:
    ordered = tuple(events)
    if any(event.occurred_at.utcoffset() is None for event in ordered):
        raise ValueError("cada evento de la simulación debe tener zona horaria")
    return tuple(sorted(ordered, key=lambda event: event.occurred_at))


class EventScheduleIterator(Iterator[SimulationEvent]):
    """Walks a sequence of events in time order, one at a time, without exposing the list.

    @pattern P14 Iterator
    """

    def __init__(self, events: Iterable[SimulationEvent]) -> None:
        self._events = _sorted_events(events)
        self._position = 0

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> SimulationEvent:
        if self._position >= len(self._events):
            raise StopIteration
        event = self._events[self._position]
        self._position += 1
        return event

    def remaining(self) -> int:
        """Number of events not yet returned."""
        return len(self._events) - self._position


class EventSchedule:
    """Aggregate of the day's events. Each `iter()` starts a new, independent iterator."""

    def __init__(self, events: Iterable[SimulationEvent]) -> None:
        self._events = _sorted_events(events)

    def __iter__(self) -> EventScheduleIterator:
        return EventScheduleIterator(self._events)

    def __len__(self) -> int:
        return len(self._events)
