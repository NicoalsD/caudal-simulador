"""Level sensors of the simulation: what the node reads from the tank at a given instant."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol


class Sensor(Protocol):
    """Interface of every sensor, including the decorators that wrap another sensor."""

    def read(self, at: datetime) -> float:
        """Level in meters that the sensor reports at `at`."""


class SourceSensor:
    """Base sensor: reports the true level of the simulated tank, without any fault."""

    def __init__(self, source: Callable[[datetime], float]) -> None:
        self._source = source

    def read(self, at: datetime) -> float:
        return self._source(at)
