"""Transition table of the simulated valve (State pattern, P18)."""

import pytest

from caudal_sim.valve_state import (
    ClosedState,
    ClosingState,
    FaultState,
    InvalidValveTransitionError,
    OpeningState,
    OpenState,
    ValveEvent,
    ValveState,
    ValveStatus,
    state_for,
)

ALL_EVENTS = list(ValveEvent)

# (current status, event, expected status). Every pair that is not listed raises an error.
VALID_TRANSITIONS: list[tuple[ValveStatus, ValveEvent, ValveStatus]] = [
    (ValveStatus.CLOSED, ValveEvent.OPEN_REQUESTED, ValveStatus.OPENING),
    (ValveStatus.CLOSED, ValveEvent.CLOSE_REQUESTED, ValveStatus.CLOSED),
    (ValveStatus.OPENING, ValveEvent.OPEN_REQUESTED, ValveStatus.OPENING),
    (ValveStatus.OPENING, ValveEvent.OPEN_LIMIT_REACHED, ValveStatus.OPEN),
    (ValveStatus.OPENING, ValveEvent.CLOSE_REQUESTED, ValveStatus.CLOSING),
    (ValveStatus.OPENING, ValveEvent.TRAVEL_TIMEOUT, ValveStatus.FAULT),
    (ValveStatus.OPEN, ValveEvent.OPEN_REQUESTED, ValveStatus.OPEN),
    (ValveStatus.OPEN, ValveEvent.CLOSE_REQUESTED, ValveStatus.CLOSING),
    (ValveStatus.CLOSING, ValveEvent.CLOSE_REQUESTED, ValveStatus.CLOSING),
    (ValveStatus.CLOSING, ValveEvent.CLOSED_LIMIT_REACHED, ValveStatus.CLOSED),
    (ValveStatus.CLOSING, ValveEvent.OPEN_REQUESTED, ValveStatus.OPENING),
    (ValveStatus.CLOSING, ValveEvent.TRAVEL_TIMEOUT, ValveStatus.FAULT),
    (ValveStatus.FAULT, ValveEvent.OPEN_REQUESTED, ValveStatus.OPENING),
    (ValveStatus.FAULT, ValveEvent.CLOSE_REQUESTED, ValveStatus.CLOSING),
]


def _is_valid(status: ValveStatus, event: ValveEvent) -> bool:
    return any(s is status and e is event for s, e, _ in VALID_TRANSITIONS)


@pytest.mark.parametrize(("status", "event", "expected"), VALID_TRANSITIONS)
def test_valid_transition_reaches_expected_status(
    status: ValveStatus, event: ValveEvent, expected: ValveStatus
) -> None:
    next_state = state_for(status).handle(event)

    assert next_state.status is expected


def test_every_invalid_pair_raises_with_status_and_event() -> None:
    checked = 0
    for status in ValveStatus:
        for event in ALL_EVENTS:
            if _is_valid(status, event):
                continue
            checked += 1
            with pytest.raises(InvalidValveTransitionError) as error:
                state_for(status).handle(event)
            assert error.value.status is status
            assert error.value.event is event

    assert checked == len(ValveStatus) * len(ALL_EVENTS) - len(VALID_TRANSITIONS)


def test_fault_is_left_only_by_a_new_order() -> None:
    fault = state_for(ValveStatus.FAULT)
    limit_events = [
        ValveEvent.OPEN_LIMIT_REACHED,
        ValveEvent.CLOSED_LIMIT_REACHED,
        ValveEvent.TRAVEL_TIMEOUT,
    ]

    for event in limit_events:
        with pytest.raises(InvalidValveTransitionError):
            fault.handle(event)


def test_reversing_a_travel_keeps_the_motor_moving_the_other_way() -> None:
    opening = OpeningState()
    closing = opening.handle(ValveEvent.CLOSE_REQUESTED)

    assert isinstance(closing, ClosingState)
    assert closing.handle(ValveEvent.OPEN_REQUESTED).status is ValveStatus.OPENING


def test_repeated_order_returns_the_same_state_object() -> None:
    open_state = OpenState()
    closed_state = ClosedState()

    assert open_state.handle(ValveEvent.OPEN_REQUESTED) is open_state
    assert closed_state.handle(ValveEvent.CLOSE_REQUESTED) is closed_state


def test_state_for_builds_the_concrete_class_of_each_status() -> None:
    expected_types: dict[ValveStatus, type[ValveState]] = {
        ValveStatus.CLOSED: ClosedState,
        ValveStatus.OPENING: OpeningState,
        ValveStatus.OPEN: OpenState,
        ValveStatus.CLOSING: ClosingState,
        ValveStatus.FAULT: FaultState,
    }

    for status, state_type in expected_types.items():
        state = state_for(status)
        assert type(state) is state_type
        assert state.status is status


def test_invalid_transition_message_is_in_spanish() -> None:
    error = InvalidValveTransitionError(ValveStatus.OPEN, ValveEvent.OPEN_LIMIT_REACHED)

    assert "no acepta el evento" in str(error)
