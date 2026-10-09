"""Climate of the simulator: wet and dry days per month."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import numpy.typing as npt

from caudal_sim.scenario import MONTHS_PER_YEAR, MonthClimate


class WetDayModel(ABC):
    """Interface (Strategy): decides which days rain within a period.

    @pattern P19 Strategy
    """

    @abstractmethod
    def wet_days(self, start: date, days: int, rng: np.random.Generator) -> npt.NDArray[np.bool_]:
        """Returns one value per day: True if the day is wet."""


class RainAmountModel(ABC):
    """Interface (Strategy): amount of rain of each day, in millimeters.

    @pattern P19 Strategy
    """

    @abstractmethod
    def amounts_mm(
        self, wet: npt.NDArray[np.bool_], start: date, rng: np.random.Generator
    ) -> npt.NDArray[np.float64]:
        """Returns the millimeters of each day. Dry days are zero."""


class MonthlyMarkovClimate(WetDayModel):
    """Two-state Markov chain (dry and wet) with probabilities per month.

    Each day uses a single uniform from the random stream. Thus the result depends only on
    the seed and the scenario, not on the order in which days are queried.

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
    """Rain on wet days with a gamma distribution, shape and scale per month.

    One amount is drawn for every day and then masked with the dry days.
    Thus the random stream does not depend on which days are wet.

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
