"""Leaks: Poisson arrivals, repair and community reports."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.scenario import LeakSpec

DAYS_PER_MONTH = 30


@dataclass(frozen=True)
class Leak:
    """A leak: starts one day, is repaired at the start of `repair_day`, and may be reported."""

    leak_id: int
    start_day: int
    repair_day: int
    flow_m3_per_hour: float
    reported_day: int | None


@dataclass(frozen=True)
class LeakRun:
    """Leaks of the period and their hourly outflow (m³ per hour)."""

    leaks: tuple[Leak, ...]
    outflow_m3_per_hour: npt.NDArray[np.float64]


class LeakProcess:
    """Poisson-arrival leaks: the number of leaks per day comes from the monthly rate.

    The number of leaks per day, their duration and the report day come from a single
    random stream in a fixed order. So the same scenario and seed always give the same
    leaks.
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
        # Days until the report (geometric from the start day). If it exceeds the repair,
        # the leak is repaired without being reported.
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
