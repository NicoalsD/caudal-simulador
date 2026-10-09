"""Clima del simulador: días húmedos y secos por mes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import numpy.typing as npt

from caudal_sim.scenario import MONTHS_PER_YEAR, MonthClimate


class WetDayModel(ABC):
    """Interfaz (Strategy): decide qué días llueve dentro de un periodo.

    @pattern P19 Strategy
    """

    @abstractmethod
    def wet_days(self, start: date, days: int, rng: np.random.Generator) -> npt.NDArray[np.bool_]:
        """Devuelve un valor por día: True si el día es húmedo."""


class MonthlyMarkovClimate(WetDayModel):
    """Cadena de Markov de dos estados (seco y húmedo) con probabilidades por mes.

    Cada día usa una única uniforme del flujo aleatorio. Así, el resultado depende solo de
    la semilla y del escenario, no del orden en que se consultan los días.

    @pattern P19 Strategy
    """

    def __init__(self, monthly: Sequence[MonthClimate]) -> None:
        self._p_after_dry = np.zeros(MONTHS_PER_YEAR + 1)
        self._p_after_wet = np.zeros(MONTHS_PER_YEAR + 1)
        for row in monthly:
            self._p_after_dry[row.month] = row.p_wet_after_dry
            self._p_after_wet[row.month] = row.p_wet_after_wet

    def wet_days(self, start: date, days: int, rng: np.random.Generator) -> npt.NDArray[np.bool_]:
        uniforms = rng.random(days)
        wet = np.zeros(days, dtype=np.bool_)
        previous_wet = False
        for index in range(days):
            month = (start + timedelta(days=index)).month
            probability = self._p_after_wet[month] if previous_wet else self._p_after_dry[month]
            previous_wet = bool(uniforms[index] < probability)
            wet[index] = previous_wet
        return wet
