"""Human readings of the tank gauge: reading noise and rounding to the gauge step."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.scenario import ReadingSpec, TankSpec

GRID_EPSILON = 1e-9
MAX_STEP_DECIMALS = 12


@dataclass(frozen=True)
class Reading:
    """Gauge reading: a number in meters, with its day and hour in the simulation."""

    reading_id: int
    day_index: int
    hour: int
    gauge_m: float


class ReadingErrorModel(ABC):
    """Interface (Strategy): turns the true level into the number the operator writes.

    @pattern P19 Strategy
    """

    @abstractmethod
    def read(
        self, true_levels_m: npt.NDArray[np.float64], rng: np.random.Generator
    ) -> npt.NDArray[np.float64]:
        """Returns the reading of each true level."""


class GaussianRoundingReadingModel(ReadingErrorModel):
    """Normal reading error, bounded to the gauge and rounded to its precision step.

    Order: noise, clipping to [gauge_min, gauge_max], rounding to the grid
    `gauge_min + k * gauge_step` and, last, the decimals of the step. The reading never falls
    outside the gauge or outside the grid.

    @pattern P19 Strategy
    """

    def __init__(self, tank: TankSpec, noise_sd_m: float) -> None:
        self._gauge_min = tank.gauge_min
        self._gauge_max = tank.gauge_max
        self._gauge_step = tank.gauge_step
        self._noise_sd_m = noise_sd_m
        self._max_step_index = math.floor(
            (tank.gauge_max - tank.gauge_min) / tank.gauge_step + GRID_EPSILON
        )
        self._decimals = len(f"{tank.gauge_step:.{MAX_STEP_DECIMALS}f}".rstrip("0").split(".")[1])

    def read(
        self, true_levels_m: npt.NDArray[np.float64], rng: np.random.Generator
    ) -> npt.NDArray[np.float64]:
        noise = rng.normal(0.0, self._noise_sd_m, size=true_levels_m.shape)
        clipped = np.clip(true_levels_m + noise, self._gauge_min, self._gauge_max)
        index = np.clip(
            np.rint((clipped - self._gauge_min) / self._gauge_step), 0, self._max_step_index
        )
        grid = self._gauge_min + index * self._gauge_step
        return np.asarray(np.round(grid, self._decimals), dtype=np.float64)


@dataclass(frozen=True)
class TransmittedReading:
    """Reading as it reaches the system: observed time, arrival time and duplicate flag."""

    reading_id: int
    observed_hour_index: int
    sent_hour_index: int
    gauge_m: float
    is_duplicate: bool
    is_delayed: bool


class TransmissionModel(ABC):
    """Interface (Strategy): decides when each reading reaches the system.

    No reading is lost: a reading without signal arrives later, and a duplicate arrives
    twice with the same `reading_id`.

    @pattern P19 Strategy
    """

    @abstractmethod
    def transmit(
        self, readings: Sequence[Reading], rng: np.random.Generator
    ) -> tuple[TransmittedReading, ...]:
        """Returns the arrivals of all readings, in arrival order."""


class NoSignalDuplicateTransmission(TransmissionModel):
    """No signal (late arrival) and duplicates, with probabilities and maximum delay.

    Each reading consumes three uniforms from the stream, in a fixed order, so the result
    depends only on the seed and the scenario.

    @pattern P19 Strategy
    """

    def __init__(self, spec: ReadingSpec) -> None:
        self._spec = spec

    def transmit(
        self, readings: Sequence[Reading], rng: np.random.Generator
    ) -> tuple[TransmittedReading, ...]:
        draws = rng.random((len(readings), 2))
        delays = rng.integers(1, self._spec.max_delay_hours + 1, size=len(readings))
        arrivals: list[TransmittedReading] = []
        for position, reading in enumerate(readings):
            observed = reading.day_index * HOURS_PER_DAY + reading.hour
            delayed = bool(draws[position, 0] < self._spec.no_signal_probability)
            sent = observed + int(delays[position]) if delayed else observed
            duplicated = bool(draws[position, 1] < self._spec.duplicate_probability)
            base = TransmittedReading(
                reading_id=reading.reading_id,
                observed_hour_index=observed,
                sent_hour_index=sent,
                gauge_m=reading.gauge_m,
                is_duplicate=False,
                is_delayed=delayed,
            )
            arrivals.append(base)
            if duplicated:
                arrivals.append(
                    TransmittedReading(
                        reading_id=base.reading_id,
                        observed_hour_index=observed,
                        sent_hour_index=sent,
                        gauge_m=base.gauge_m,
                        is_duplicate=True,
                        is_delayed=delayed,
                    )
                )
        arrivals.sort(key=lambda item: (item.sent_hour_index, item.reading_id, item.is_duplicate))
        return tuple(arrivals)


def take_readings(
    levels_m: npt.NDArray[np.float64],
    days: int,
    reading_hours: Sequence[int],
    model: ReadingErrorModel,
    rng: np.random.Generator,
) -> tuple[Reading, ...]:
    """Operator readings: each day, at the given hours, through the error model."""
    indices = np.array(
        [day * HOURS_PER_DAY + hour for day in range(days) for hour in reading_hours],
        dtype=np.int64,
    )
    observed = model.read(levels_m[indices], rng)
    return tuple(
        Reading(
            reading_id=reading_id,
            day_index=int(index) // HOURS_PER_DAY,
            hour=int(index) % HOURS_PER_DAY,
            gauge_m=float(value),
        )
        for reading_id, (index, value) in enumerate(zip(indices, observed, strict=True))
    )
