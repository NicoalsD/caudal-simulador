"""Open and close commands with their time window (Command, P13)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from caudal_sim.actuator_driver import SimulatedMotorDriver
from caudal_sim.valve_actuator import ValveActuator
from caudal_sim.valve_commands import CloseValveCommand, OpenValveCommand, ValveCommandKind
from caudal_sim.valve_state import ValveStatus

COMMAND_ID = UUID("0190f3a2-7777-7000-8000-000000000001")
VALVE_ID = UUID("0190f3a2-7777-7000-8000-000000000002")
NOT_BEFORE = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
EXPIRES_AT = NOT_BEFORE + timedelta(minutes=10)
BEFORE_WINDOW = NOT_BEFORE - timedelta(seconds=1)
AT_START = NOT_BEFORE
INSIDE = NOT_BEFORE + timedelta(minutes=5)
AT_EXPIRY = EXPIRES_AT
AFTER_EXPIRY = EXPIRES_AT + timedelta(seconds=1)
TRAVEL_TIME = timedelta(seconds=15)
MAX_TRAVEL_TIME = timedelta(seconds=60)


def _valve() -> ValveActuator:
    return ValveActuator(SimulatedMotorDriver(TRAVEL_TIME), MAX_TRAVEL_TIME)


def test_open_command_asks_the_valve_to_open_inside_the_window() -> None:
    command = OpenValveCommand(COMMAND_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT)
    valve = _valve()

    applied = command.execute(INSIDE, valve)

    assert applied is True
    assert valve.status is ValveStatus.OPENING
    assert command.kind is ValveCommandKind.OPEN


def test_close_command_asks_the_valve_to_close_inside_the_window() -> None:
    command = CloseValveCommand(COMMAND_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT)
    valve = _valve()
    valve.request_open()

    applied = command.execute(INSIDE, valve)

    assert applied is True
    assert valve.status is ValveStatus.CLOSING
    assert command.kind is ValveCommandKind.CLOSE


def test_window_includes_the_start_and_excludes_the_expiry() -> None:
    command = OpenValveCommand(COMMAND_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT)

    assert command.is_executable_at(AT_START) is True
    assert command.is_executable_at(AT_EXPIRY) is False


def test_expired_command_never_reaches_the_valve() -> None:
    command = OpenValveCommand(COMMAND_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT)
    valve = _valve()

    applied = command.execute(AFTER_EXPIRY, valve)

    assert applied is False
    assert valve.status is ValveStatus.CLOSED


def test_early_command_does_not_move_the_valve() -> None:
    command = CloseValveCommand(COMMAND_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT)
    valve = _valve()
    valve.request_open()

    applied = command.execute(BEFORE_WINDOW, valve)

    assert applied is False
    assert valve.status is ValveStatus.OPENING


def test_window_must_end_after_it_starts() -> None:
    with pytest.raises(ValueError, match="vencer después"):
        OpenValveCommand(COMMAND_ID, VALVE_ID, NOT_BEFORE, NOT_BEFORE)


def test_naive_timestamps_are_rejected() -> None:
    naive_start = datetime(2026, 1, 1, 6, 0)

    with pytest.raises(ValueError, match="zona horaria"):
        OpenValveCommand(COMMAND_ID, VALVE_ID, naive_start, EXPIRES_AT)


def test_command_exposes_its_identity_and_window() -> None:
    command = CloseValveCommand(COMMAND_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT)

    assert command.command_id == COMMAND_ID
    assert command.valve_id == VALVE_ID
    assert command.not_before == NOT_BEFORE
    assert command.expires_at == EXPIRES_AT
