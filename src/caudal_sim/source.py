"""Caudal de la fuente: caudal base más respuesta a la lluvia con retardo."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.scenario import SourceSpec


@dataclass(frozen=True)
class SourceSeries:
    """Caudal horario de la fuente y la bandera de agua con barro."""

    flow_m3_per_hour: npt.NDArray[np.float64]
    muddy_water: npt.NDArray[np.bool_]


class InflowModel(ABC):
    """Interfaz (Strategy): caudal de la fuente a partir de la lluvia diaria.

    @pattern P19 Strategy
    """

    @abstractmethod
    def simulate(self, daily_rain_mm: npt.NDArray[np.float64]) -> SourceSeries:
        """Devuelve el caudal y la turbiedad de cada hora del periodo."""


class LaggedRainSource(InflowModel):
    """Caudal base más una respuesta exponencial a la lluvia, con retardo.

    La lluvia diaria se reparte en partes iguales entre las horas del día (supuesto).
    Cada hora, la respuesta acumulada decae con la constante `response_lag_hours`.
    Un día con lluvia igual o mayor al umbral deja el agua con barro durante varias horas.

    @pattern P19 Strategy
    """

    def __init__(self, spec: SourceSpec) -> None:
        self._spec = spec
        self._decay = math.exp(-1.0 / spec.response_lag_hours)

    def simulate(self, daily_rain_mm: npt.NDArray[np.float64]) -> SourceSeries:
        days = daily_rain_mm.shape[0]
        hours = days * HOURS_PER_DAY
        hourly_rain = np.repeat(daily_rain_mm / HOURS_PER_DAY, HOURS_PER_DAY)

        response = np.zeros(hours, dtype=np.float64)
        accumulated = 0.0
        for hour in range(hours):
            accumulated = accumulated * self._decay + hourly_rain[hour]
            response[hour] = accumulated

        flow = self._spec.base_flow_m3_per_hour + self._spec.rain_gain_m3_per_hour_per_mm * response

        muddy = np.zeros(hours, dtype=np.bool_)
        for day in np.flatnonzero(daily_rain_mm >= self._spec.muddy_rain_threshold_mm):
            start = int(day) * HOURS_PER_DAY
            end = min(hours, start + self._spec.muddy_duration_hours)
            muddy[start:end] = True

        return SourceSeries(flow_m3_per_hour=flow, muddy_water=muddy)
