"""Ordered traversal of the simulation events of a day (Iterator, P14)."""

from datetime import UTC, datetime, timedelta

import pytest

from caudal_sim.event_bus import SimulationEvent, SimulationEventKind
from caudal_sim.event_schedule import EventSchedule, EventScheduleIterator

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
ONE_MINUTE = timedelta(minutes=1)
TWO_EVENTS = 2
ONE_EVENT = 1


def _event(minutes: int, detail: str) -> SimulationEvent:
    return SimulationEvent(
        occurred_at=START + minutes * ONE_MINUTE,
        kind=SimulationEventKind.COMMAND_DELIVERED,
        subject_id="valve-bajo",
        detail=detail,
    )


def test_events_come_out_in_time_order_whatever_the_input_order() -> None:
    events = [_event(30, "third"), _event(5, "first"), _event(10, "second")]

    details = [event.detail for event in EventScheduleIterator(events)]

    assert details == ["first", "second", "third"]


def test_events_at_the_same_instant_keep_their_written_order() -> None:
    events = [_event(5, "written-first"), _event(5, "written-second"), _event(1, "early")]

    details = [event.detail for event in EventScheduleIterator(events)]

    assert details == ["early", "written-first", "written-second"]


def test_iterator_stops_and_keeps_stopping_when_exhausted() -> None:
    iterator = EventScheduleIterator([_event(1, "only")])

    assert next(iterator).detail == "only"
    with pytest.raises(StopIteration):
        next(iterator)
    with pytest.raises(StopIteration):
        next(iterator)


def test_remaining_counts_events_not_yet_returned() -> None:
    iterator = EventScheduleIterator([_event(1, "a"), _event(2, "b")])

    assert iterator.remaining() == TWO_EVENTS
    next(iterator)
    assert iterator.remaining() == ONE_EVENT


def test_empty_schedule_yields_nothing() -> None:
    assert list(EventScheduleIterator([])) == []
    assert len(EventSchedule([])) == 0


def test_each_iteration_of_the_aggregate_starts_from_the_beginning() -> None:
    schedule = EventSchedule([_event(5, "a"), _event(1, "b")])

    first_pass = [event.detail for event in schedule]
    second_pass = [event.detail for event in schedule]

    assert first_pass == second_pass == ["b", "a"]
    assert len(schedule) == TWO_EVENTS


def test_two_iterators_over_the_same_schedule_advance_independently() -> None:
    schedule = EventSchedule([_event(1, "a"), _event(2, "b")])
    first = iter(schedule)
    second = iter(schedule)

    assert next(first).detail == "a"
    assert next(first).detail == "b"
    assert next(second).detail == "a"


def test_naive_timestamps_are_rejected() -> None:
    naive = SimulationEvent(
        occurred_at=datetime(2026, 1, 1, 0, 0),
        kind=SimulationEventKind.COMMAND_CONFIRMED,
        subject_id="valve-bajo",
        detail="naive",
    )

    with pytest.raises(ValueError, match="zona horaria"):
        EventScheduleIterator([naive])
