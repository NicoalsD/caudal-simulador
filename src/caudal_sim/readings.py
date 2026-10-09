"""Lecturas humanas de la regla del tanque: ruido de lectura y redondeo al paso de la regla."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.scenario import TankSpec

GRID_EPSILON = 1e-9
MAX_STEP_DECIMALS = 12


@dataclass(frozen=True)
class Reading:
    """Lectura de la regla: un número en metros, con su día y su hora en la simulación."""

    reading_id: int
    day_index: int
    hour: int
    gauge_m: float


class ReadingErrorModel(ABC):
    """Interfaz (Strategy): convierte el nivel real en el número que anota el fontanero.

    @pattern P19 Strategy
    """

    @abstractmethod
    def read(
        self, true_levels_m: npt.NDArray[np.float64], rng: np.random.Generator
    ) -> npt.NDArray[np.float64]:
        """Devuelve la lectura de cada nivel real."""


class GaussianRoundingReadingModel(ReadingErrorModel):
    """Error normal de lectura, acotado a la regla y redondeado a su paso de precisión.

    Orden: ruido, recorte a [gauge_min, gauge_max], redondeo a la rejilla
    `gauge_min + k * gauge_step` y, por último, los decimales del paso. La lectura nunca cae
    fuera de la regla ni fuera de la rejilla.

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


def take_readings(
    levels_m: npt.NDArray[np.float64],
    days: int,
    reading_hours: Sequence[int],
    model: ReadingErrorModel,
    rng: np.random.Generator,
) -> tuple[Reading, ...]:
    """Lecturas del fontanero: en cada día, a las horas indicadas, con el modelo de error."""
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
