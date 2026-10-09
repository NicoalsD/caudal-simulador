"""Level sensors of the simulation: what the node reads from the tank at a given instant."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np

ONE_DAY = timedelta(days=1)


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


class NoisySensor:
    """Adds Gaussian noise to the reading of another sensor, for example the ADS1115 quantization.

    The noise comes from the shared random generator of the run, so it depends on the seed.

    @pattern P09 Decorator
    """

    def __init__(self, inner: Sensor, rng: np.random.Generator, sigma_m: float) -> None:
        if sigma_m < 0:
            raise ValueError("la desviación del ruido no puede ser negativa")
        self._inner = inner
        self._rng = rng
        self._sigma_m = sigma_m

    def read(self, at: datetime) -> float:
        return self._inner.read(at) + float(self._rng.normal(0.0, self._sigma_m))


class StuckSensor:
    """Freezes the reading of another sensor inside a window: the first value read stays.

    Outside the window the decorator passes the inner readings through. The frozen value is
    part of the state, so a snapshot taken inside the window keeps it.

    @pattern P09 Decorator
    """

    def __init__(self, inner: Sensor, stuck_from: datetime, stuck_until: datetime) -> None:
        if stuck_until <= stuck_from:
            raise ValueError("la ventana del valor pegado debe terminar después de empezar")
        self._inner = inner
        self._stuck_from = stuck_from
        self._stuck_until = stuck_until
        self._frozen: float | None = None

    def read(self, at: datetime) -> float:
        if not self._stuck_from <= at < self._stuck_until:
            self._frozen = None
            return self._inner.read(at)
        if self._frozen is None:
            self._frozen = self._inner.read(at)
        return self._frozen

    def capture(self) -> float | None:
        """Frozen value, or None when the sensor is not stuck."""
        return self._frozen

    def restore(self, state: float | None) -> None:
        """Puts back the frozen value saved in a snapshot."""
        self._frozen = state


class DriftingSensor:
    """Adds a linear drift to the reading of another sensor, from `drift_start` on.

    The offset is `drift_m_per_day` times the days since `drift_start`. It is a pure function
    of the instant, so the decorator keeps no state.

    @pattern P09 Decorator
    """

    def __init__(self, inner: Sensor, drift_m_per_day: float, drift_start: datetime) -> None:
        self._inner = inner
        self._drift_m_per_day = drift_m_per_day
        self._drift_start = drift_start

    def read(self, at: datetime) -> float:
        elapsed = at - self._drift_start
        days = max(elapsed, timedelta(0)) / ONE_DAY
        return self._inner.read(at) + self._drift_m_per_day * days
