"""Bridge between the valve logic and the motor driver (P07), with the valve States."""

from datetime import timedelta

import pytest

from caudal_sim.actuator_driver import ActuatorDriver, MotorDirection, SimulatedMotorDriver
from caudal_sim.valve_actuator import ValveActuator
from caudal_sim.valve_state import ValveStatus

TRAVEL_TIME = timedelta(seconds=15)
MAX_TRAVEL_TIME = timedelta(seconds=60)
PARTIAL_TRAVEL = timedelta(seconds=5)


def _valve(*, stalled: bool = False) -> tuple[ValveActuator, SimulatedMotorDriver]:
    driver = SimulatedMotorDriver(TRAVEL_TIME, stalled=stalled)
    return ValveActuator(driver, MAX_TRAVEL_TIME), driver


def test_valve_starts_closed_with_the_motor_stopped() -> None:
    valve, driver = _valve()

    assert valve.status is ValveStatus.CLOSED
    assert driver.direction is None


def test_valve_opens_after_its_travel_time_and_the_motor_stops() -> None:
    valve, driver = _valve()

    valve.request_open()
    valve.advance(PARTIAL_TRAVEL)
    assert valve.status is ValveStatus.OPENING
    assert driver.direction is MotorDirection.OPEN

    valve.advance(TRAVEL_TIME - PARTIAL_TRAVEL)
    assert valve.status is ValveStatus.OPEN
    assert driver.direction is None


def test_valve_closes_after_its_travel_time() -> None:
    valve, driver = _valve()
    valve.request_open()
    valve.advance(TRAVEL_TIME)

    valve.request_close()
    valve.advance(TRAVEL_TIME)

    assert valve.status is ValveStatus.CLOSED
    assert driver.direction is None


def test_time_passes_without_effect_when_the_valve_is_not_travelling() -> None:
    valve, driver = _valve()

    valve.advance(MAX_TRAVEL_TIME)

    assert valve.status is ValveStatus.CLOSED
    assert driver.direction is None


def test_reversing_a_travel_switches_the_motor_and_restarts_the_clock() -> None:
    valve, driver = _valve()
    valve.request_open()
    valve.advance(TRAVEL_TIME - PARTIAL_TRAVEL)

    valve.request_close()
    valve.advance(PARTIAL_TRAVEL)

    assert valve.status is ValveStatus.CLOSING
    assert driver.direction is MotorDirection.CLOSE


def test_stalled_motor_faults_at_the_maximum_travel_time() -> None:
    valve, driver = _valve(stalled=True)
    valve.request_open()

    valve.advance(MAX_TRAVEL_TIME - PARTIAL_TRAVEL)
    assert valve.status is ValveStatus.OPENING

    valve.advance(PARTIAL_TRAVEL)
    assert valve.status is ValveStatus.FAULT
    assert driver.direction is None


def test_fault_is_left_only_by_a_new_order_that_starts_the_motor_again() -> None:
    valve, driver = _valve(stalled=True)
    valve.request_open()
    valve.advance(MAX_TRAVEL_TIME)

    valve.advance(MAX_TRAVEL_TIME)
    assert valve.status is ValveStatus.FAULT

    valve.request_close()
    assert valve.status is ValveStatus.CLOSING
    assert driver.direction is MotorDirection.CLOSE


def test_valve_accepts_any_driver_that_implements_the_interface() -> None:
    class ScriptedDriver(ActuatorDriver):
        def __init__(self) -> None:
            self.calls: list[str] = []

        @property
        def travel_time(self) -> timedelta:
            return TRAVEL_TIME

        def start(self, direction: MotorDirection) -> None:
            self.calls.append(f"start {direction}")

        def stop(self) -> None:
            self.calls.append("stop")

        def limit_reached_after(self, travelled: timedelta) -> bool:
            return travelled >= TRAVEL_TIME

    driver = ScriptedDriver()
    valve = ValveActuator(driver, MAX_TRAVEL_TIME)

    valve.request_open()
    valve.advance(TRAVEL_TIME)

    assert driver.calls == ["start OPEN", "stop"]


def test_maximum_travel_time_cannot_be_shorter_than_the_travel() -> None:
    driver = SimulatedMotorDriver(TRAVEL_TIME)

    with pytest.raises(ValueError, match="no puede ser menor"):
        ValveActuator(driver, TRAVEL_TIME - PARTIAL_TRAVEL)


def test_driver_rejects_non_positive_travel_time() -> None:
    with pytest.raises(ValueError, match="mayor que cero"):
        SimulatedMotorDriver(timedelta(0))


def test_valve_rejects_negative_elapsed_time() -> None:
    valve, _ = _valve()

    with pytest.raises(ValueError, match="no puede ser negativo"):
        valve.advance(-PARTIAL_TRAVEL)
