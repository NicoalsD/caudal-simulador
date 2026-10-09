"""Abstract Factory of field kits (P03)."""

from datetime import UTC, datetime, timedelta

from caudal_sim.actuator_driver import SimulatedMotorDriver
from caudal_sim.device_kit import DeviceKit, DeviceKitFactory, FieldKitFactory
from caudal_sim.sensors import Sensor
from caudal_sim.valve_actuator import Actuator, ValveActuator
from caudal_sim.valve_state import ValveStatus

AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
TRAVEL_TIME = timedelta(seconds=15)
MAX_TRAVEL_TIME = timedelta(seconds=60)
TANK_LEVEL_M = 3.4


def _tank_level(_at: datetime) -> float:
    return TANK_LEVEL_M


def _field_factory() -> FieldKitFactory:
    return FieldKitFactory(_tank_level, TRAVEL_TIME, MAX_TRAVEL_TIME)


def test_kit_holds_a_sensor_and_an_actuator_from_the_same_family() -> None:
    kit = _field_factory().create_kit()

    assert isinstance(kit, DeviceKit)
    assert kit.sensor.read(AT) == TANK_LEVEL_M
    assert kit.actuator.status is ValveStatus.CLOSED


def test_each_kit_gets_its_own_actuator() -> None:
    factory = _field_factory()

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
            return ValveActuator(SimulatedMotorDriver(TRAVEL_TIME), MAX_TRAVEL_TIME)

    def read_tank(factory: DeviceKitFactory) -> float:
        return factory.create_kit().sensor.read(AT)

    assert read_tank(BenchFactory()) == TANK_LEVEL_M
    assert read_tank(_field_factory()) == TANK_LEVEL_M
