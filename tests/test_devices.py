"""Factory Method for simulated devices (P02)."""

from uuid import UUID

import pytest

from caudal_sim.devices import (
    MAX_DEVICE_NAME_LENGTH,
    DeviceCreator,
    DeviceKind,
    LevelSensorCreator,
    SimulatedDevice,
    ValveNodeCreator,
)

DEVICE_ID = UUID("0190f3a2-9999-7000-8000-000000000001")


def test_level_sensor_creator_builds_a_level_sensor() -> None:
    device = LevelSensorCreator().create(DEVICE_ID, "Sensor tanque")

    assert device == SimulatedDevice(
        device_id=DEVICE_ID, name="Sensor tanque", kind=DeviceKind.LEVEL_SENSOR
    )


def test_valve_node_creator_builds_a_valve_node() -> None:
    device = ValveNodeCreator().create(DEVICE_ID, "Nodo sector alto")

    assert device.kind is DeviceKind.VALVE_NODE
    assert device.device_id == DEVICE_ID


def test_name_is_stripped_before_the_product_is_built() -> None:
    device = ValveNodeCreator().create(DEVICE_ID, "  Nodo bajo  ")

    assert device.name == "Nodo bajo"


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_name_is_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="no puede estar vacío"):
        LevelSensorCreator().create(DEVICE_ID, name)


def test_name_at_the_limit_is_accepted_and_one_more_character_is_not() -> None:
    at_limit = "a" * MAX_DEVICE_NAME_LENGTH

    assert LevelSensorCreator().create(DEVICE_ID, at_limit).name == at_limit
    with pytest.raises(ValueError, match="no puede superar"):
        LevelSensorCreator().create(DEVICE_ID, at_limit + "a")


def test_callers_can_use_any_creator_through_the_abstract_type() -> None:
    creators: list[DeviceCreator] = [LevelSensorCreator(), ValveNodeCreator()]

    kinds = [creator.create(DEVICE_ID, "nodo").kind for creator in creators]

    assert kinds == [DeviceKind.LEVEL_SENSOR, DeviceKind.VALVE_NODE]


def test_devices_are_immutable() -> None:
    device = LevelSensorCreator().create(DEVICE_ID, "Sensor tanque")

    with pytest.raises(AttributeError):
        device.name = "otro"  # type: ignore[misc]
