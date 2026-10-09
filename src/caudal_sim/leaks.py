"""Fugas: llegadas por proceso de Poisson, reparación y reporte de la comunidad."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.scenario import LeakSpec

DAYS_PER_MONTH = 30


@dataclass(frozen=True)
class Leak:
    """Una fuga: empieza un día, se repara al inicio de `repair_day` y puede ser reportada."""

    leak_id: int
    start_day: int
    repair_day: int
    flow_m3_per_hour: float
    reported_day: int | None


@dataclass(frozen=True)
class LeakRun:
    """Fugas del periodo y su caudal de salida por hora (m³ por hora)."""

    leaks: tuple[Leak, ...]
    outflow_m3_per_hour: npt.NDArray[np.float64]


class LeakProcess:
    """Fugas de llegada Poisson: la cantidad de fugas por día sale de la tasa mensual.

    La cantidad de fugas por día, la duración y el día del reporte salen de un único flujo
    aleatorio y en un orden fijo. Por eso el mismo escenario y la misma semilla dan siempre
    las mismas fugas.
    """

    def __init__(self, spec: LeakSpec) -> None:
        self._spec = spec

    def simulate(self, days: int, rng: np.random.Generator) -> LeakRun:
        daily_rate = self._spec.rate_per_month / DAYS_PER_MONTH
        arrivals = rng.poisson(daily_rate, size=days)
        starts = np.repeat(np.arange(days), arrivals)
        count = int(starts.shape[0])

        repair_days = rng.integers(
            self._spec.repair_days_min, self._spec.repair_days_max + 1, size=count
        )
        # Días hasta el reporte (geométrica desde el día de inicio). Si pasa de la reparación,
        # la fuga se repara sin reportarse.
        delays = rng.geometric(self._spec.report_probability_per_day, size=count) - 1

        leaks: list[Leak] = []
        outflow = np.zeros(days * HOURS_PER_DAY, dtype=np.float64)
        for leak_id in range(count):
            start_day = int(starts[leak_id])
            duration = int(repair_days[leak_id])
            repair_day = start_day + duration
            delay = int(delays[leak_id])
            reported_day = start_day + delay if delay < duration else None
            leaks.append(
                Leak(
                    leak_id=leak_id,
                    start_day=start_day,
                    repair_day=repair_day,
                    flow_m3_per_hour=self._spec.flow_m3_per_hour,
                    reported_day=reported_day,
                )
            )
            outflow[start_day * HOURS_PER_DAY : repair_day * HOURS_PER_DAY] += (
                self._spec.flow_m3_per_hour
            )
        return LeakRun(leaks=tuple(leaks), outflow_m3_per_hour=outflow)
