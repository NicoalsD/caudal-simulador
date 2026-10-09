"""Abstract Factory of field kits (P03) and the valve actuator it assembles."""

from datetime import UTC, datetime, timedelta

import pytest

from caudal_sim.device_kit import DeviceKit, DeviceKitFactory, FieldKitFactory
from caudal_sim.sensors import Sensor
from caudal_sim.valve_actuator import Actuator, ValveActuator
from caudal_sim.valve_state import ValveStatus

AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
TRAVEL_TIME = timedelta(seconds=15)
TANK_LEVEL_M = 3.4
PARTIAL_TRAVEL = timedelta(seconds=5)


def _tank_level(_at: datetime) -> float:
    return TANK_LEVEL_M


def test_kit_holds_a_sensor_and_an_actuator_from_the_same_family() -> None:
    kit = FieldKitFactory(_tank_level, TRAVEL_TIME).create_kit()

    assert isinstance(kit, DeviceKit)
    assert kit.sensor.read(AT) == TANK_LEVEL_M
    assert kit.actuator.status is ValveStatus.CLOSED


def test_each_kit_gets_its_own_actuator() -> None:
    factory = FieldKitFactory(_tank_level, TRAVEL_TIME)

    first = factory.create_kit()
    second = factory.create_kit()
    first.actuator.request_open()

    assert first.actuator.status is ValveStatus.OPENING
    assert second.actuator.status is ValveStatus.CLOSED


def test_client_code_depends_only_on_the_abstract_factory() -> None:
    class FixedSensor:
        def read(self, at: datetime) -> float:
            return TANK_LEVEL_M

    class BenchFactory(DeviceKitFactory):
        def create_sensor(self) -> Sensor:
            return FixedSensor()

        def create_actuator(self) -> Actuator:
            return ValveActuator(TRAVEL_TIME)

    def read_tank(factory: DeviceKitFactory) -> float:
        return factory.create_kit().sensor.read(AT)

    assert read_tank(BenchFactory()) == TANK_LEVEL_M
    assert read_tank(FieldKitFactory(_tank_level, TRAVEL_TIME)) == TANK_LEVEL_M


def test_actuator_opens_only_after_its_travel_time() -> None:
    actuator = ValveActuator(TRAVEL_TIME)

    actuator.request_open()
    actuator.advance(PARTIAL_TRAVEL)
    assert actuator.status is ValveStatus.OPENING

    actuator.advance(TRAVEL_TIME - PARTIAL_TRAVEL)
    assert actuator.status is ValveStatus.OPEN


def test_still_valve_ignores_elapsed_time() -> None:
    actuator = ValveActuator(TRAVEL_TIME)
    actuator.advance(TRAVEL_TIME)
    assert actuator.status is ValveStatus.CLOSED

    actuator.request_open()
    actuator.advance(TRAVEL_TIME)
    actuator.request_close()
    actuator.advance(TRAVEL_TIME)

    assert actuator.status is ValveStatus.CLOSED


def test_reversing_a_travel_restarts_the_travel_time() -> None:
    actuator = ValveActuator(TRAVEL_TIME)
    actuator.request_open()
    actuator.advance(TRAVEL_TIME - PARTIAL_TRAVEL)

    actuator.request_close()
    actuator.advance(PARTIAL_TRAVEL)

    assert actuator.status is ValveStatus.CLOSING


def test_actuator_rejects_non_positive_travel_time() -> None:
    with pytest.raises(ValueError, match="mayor que cero"):
        ValveActuator(timedelta(0))


def test_actuator_rejects_negative_elapsed_time() -> None:
    actuator = ValveActuator(TRAVEL_TIME)

    with pytest.raises(ValueError, match="no puede ser negativo"):
        actuator.advance(-PARTIAL_TRAVEL)
