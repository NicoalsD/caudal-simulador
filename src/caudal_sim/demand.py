"""Hourly demand per sector: households, people, per-capita allowance and daily profile."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from caudal_sim.scenario import DemandSpec, SectorSpec

LITERS_PER_CUBIC_METER = 1000.0


class SectorDemandModel:
    """Demand requested by each sector in each hour, in m³.

    Demand = sector people times daily allowance times hourly profile fraction.
    People are drawn once per sector, in scenario order, and kept for the whole
    simulation. This model does not decide whether water flows: that depends on the
    sector's open valve.

    Without @pattern: it is a direct demand calculation.
    """

    def __init__(self, sectors: Sequence[SectorSpec], demand: DemandSpec) -> None:
        self._sectors = list(sectors)
        self._demand = demand
        weights = np.array(demand.hourly_weights, dtype=np.float64)
        self._profile: npt.NDArray[np.float64] = weights / weights.sum()

    def residents(self, rng: np.random.Generator) -> dict[str, int]:
        """People per sector: sum of the random draw of people in each household."""
        residents: dict[str, int] = {}
        for sector in self._sectors:
            per_household = rng.integers(
                self._demand.persons_min, self._demand.persons_max + 1, size=sector.households
            )
            residents[sector.id] = int(per_household.sum())
        return residents

    def daily_volume_m3(self, residents: int) -> float:
        """Daily volume of a sector with those people, in m³."""
        liters = residents * self._demand.liters_per_person_per_day
        return liters / LITERS_PER_CUBIC_METER

    def hourly_demand_m3(
        self, days: int, rng: np.random.Generator
    ) -> dict[str, npt.NDArray[np.float64]]:
        """Hourly demand of each sector over `days` days, in m³ per hour."""
        residents = self.residents(rng)
        return {
            sector_id: np.tile(self._profile * self.daily_volume_m3(people), days)
            for sector_id, people in residents.items()
        }
