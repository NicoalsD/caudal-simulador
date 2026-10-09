"""Kits of a field node: the sensor and the actuator that a node needs, made by one factory.

The kit does not know which concrete classes it holds. A different family (for example, a
bench with a fixed sensor) only needs another `DeviceKitFactory`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from caudal_sim.actuator_driver import SimulatedMotorDriver
from caudal_sim.sensors import Sensor, SourceSensor
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
    """Family of the simulated field node: a sensor that reads the tank and a motorized valve."""

    def __init__(
        self,
        tank_level: Callable[[datetime], float],
        valve_travel_time: timedelta,
        valve_max_travel_time: timedelta,
    ) -> None:
        self._tank_level = tank_level
        self._valve_travel_time = valve_travel_time
        self._valve_max_travel_time = valve_max_travel_time

    def create_sensor(self) -> Sensor:
        return SourceSensor(self._tank_level)

    def create_actuator(self) -> Actuator:
        driver = SimulatedMotorDriver(self._valve_travel_time)
        return ValveActuator(driver, self._valve_max_travel_time)
