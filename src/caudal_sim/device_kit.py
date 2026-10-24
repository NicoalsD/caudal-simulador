"""Kits of a field node: the sensor and the actuator that a node needs, made by one factory.

The kit does not know which concrete classes it holds. A different family (for example, a
bench with a fixed sensor) only needs another `DeviceKitFactory`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from caudal_sim.actuator_driver import SimulatedMotorDriver
from caudal_sim.scenario import DevicesSpec
from caudal_sim.sensors import Sensor, level_sensor_from_spec
from caudal_sim.valve_actuator import Actuator, ValveActuator


@dataclass(frozen=True)
class DeviceKit:
    """Sensor and actuator of one node, created by the same family."""

    sensor: Sensor
    actuator: Actuator


class DeviceKitFactory(ABC):
    """Abstract factory: one method per product of the family, plus the kit that joins them.

    @pattern P03 Abstract Factory
    """

    @abstractmethod
    def create_sensor(self) -> Sensor:
        """Sensor of the family."""

    @abstractmethod
    def create_actuator(self) -> Actuator:
        """Actuator of the family."""

    def create_kit(self) -> DeviceKit:
        """Builds a sensor and an actuator from the same family."""
        return DeviceKit(sensor=self.create_sensor(), actuator=self.create_actuator())


class FieldKitFactory(DeviceKitFactory):
    """Family of the simulated field node: a level sensor and a motorized valve.

    Use `from_spec` so that every timing and fault value comes from the scenario.
    """

    def __init__(
        self,
        sensor_chain: Callable[[], Sensor],
        valve_travel_time: timedelta,
        valve_max_travel_time: timedelta,
    ) -> None:
        self._sensor_chain = sensor_chain
        self._valve_travel_time = valve_travel_time
        self._valve_max_travel_time = valve_max_travel_time

    @classmethod
    def from_spec(
        cls,
        devices: DevicesSpec,
        *,
        tank_level: Callable[[datetime], float],
        start: datetime,
        rng: np.random.Generator,
    ) -> FieldKitFactory:
        """Builds the family with the sensor faults and the valve times of the scenario."""
        return cls(
            lambda: level_sensor_from_spec(tank_level, devices.sensor, start, rng),
            timedelta(seconds=devices.valve.travel_seconds),
            timedelta(seconds=devices.valve.max_travel_seconds),
        )

    def create_sensor(self) -> Sensor:
        return self._sensor_chain()

    def create_actuator(self) -> Actuator:
        driver = SimulatedMotorDriver(self._valve_travel_time)
        return ValveActuator(driver, self._valve_max_travel_time)
