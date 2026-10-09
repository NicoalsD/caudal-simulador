"""Motor drivers of the valve actuators: what the motor does, whatever the valve logic is.

A driver drives the motor and tells whether the limit switch closes after a given travel.
The simulated driver reproduces the travel time of a motor and can stall it, so that the
valve reaches its timeout. A real GPIO driver would implement the same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from enum import StrEnum


class MotorDirection(StrEnum):
    """Direction in which the motor turns the valve."""

    OPEN = "OPEN"
    CLOSE = "CLOSE"


class ActuatorDriver(ABC):
    """Implementor interface of the valve bridge.

    @pattern P07 Bridge
    """

    @property
    @abstractmethod
    def travel_time(self) -> timedelta:
        """Nominal time to go from one limit switch to the other."""

    @abstractmethod
    def start(self, direction: MotorDirection) -> None:
        """Energizes the motor in `direction`."""

    @abstractmethod
    def stop(self) -> None:
        """Cuts the power to the motor."""

    @abstractmethod
    def limit_reached_after(self, travelled: timedelta) -> bool:
        """Whether the limit switch of the travel has closed after `travelled` of motion."""


class SimulatedMotorDriver(ActuatorDriver):
    """Driver with a fixed travel time. A stalled motor never reaches its limit switch."""

    def __init__(self, travel_time: timedelta, *, stalled: bool = False) -> None:
        if travel_time <= timedelta(0):
            raise ValueError("el tiempo de recorrido del motor debe ser mayor que cero")
        self._travel_time = travel_time
        self._stalled = stalled
        self._direction: MotorDirection | None = None

    @property
    def travel_time(self) -> timedelta:
        return self._travel_time

    @property
    def direction(self) -> MotorDirection | None:
        """Direction the motor is turning, or None when it is stopped."""
        return self._direction

    def start(self, direction: MotorDirection) -> None:
        self._direction = direction

    def stop(self) -> None:
        self._direction = None

    def limit_reached_after(self, travelled: timedelta) -> bool:
        return not self._stalled and travelled >= self._travel_time
