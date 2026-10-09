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


class RainAmountModel(ABC):
    """Interfaz (Strategy): cantidad de lluvia de cada día, en milímetros.

    @pattern P19 Strategy
    """

    @abstractmethod
    def amounts_mm(
        self, wet: npt.NDArray[np.bool_], start: date, rng: np.random.Generator
    ) -> npt.NDArray[np.float64]:
        """Devuelve los milímetros de cada día. Los días secos valen cero."""


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


class GammaRainfall(RainAmountModel):
    """Lluvia de los días húmedos con distribución gamma, forma y escala por mes.

    Se sortea un monto para todos los días y después se enmascara con los días secos.
    Así, el flujo aleatorio no depende de qué días son húmedos.

    @pattern P19 Strategy
    """

    def __init__(self, monthly: Sequence[MonthClimate]) -> None:
        self._shape = np.ones(MONTHS_PER_YEAR + 1)
        self._scale = np.ones(MONTHS_PER_YEAR + 1)
        for row in monthly:
            self._shape[row.month] = row.gamma_shape
            self._scale[row.month] = row.gamma_scale_mm

    def amounts_mm(
        self, wet: npt.NDArray[np.bool_], start: date, rng: np.random.Generator
    ) -> npt.NDArray[np.float64]:
        months = np.array([(start + timedelta(days=i)).month for i in range(wet.shape[0])])
        draws = rng.gamma(self._shape[months], self._scale[months])
        return np.where(wet, draws, 0.0).astype(np.float64)
