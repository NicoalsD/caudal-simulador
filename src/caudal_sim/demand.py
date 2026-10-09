"""Demanda horaria por sector: hogares, personas, dotación y perfil del día."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from caudal_sim.scenario import DemandSpec, SectorSpec

LITERS_PER_CUBIC_METER = 1000.0


class SectorDemandModel:
    """Demanda que pide cada sector en cada hora, en m³.

    Demanda = personas del sector por dotación diaria por fracción del perfil horario.
    Las personas se sortean una vez por sector, en el orden del escenario, y se mantienen
    durante toda la simulación. Este modelo no decide si el agua sale: eso depende de la
    válvula abierta del sector.

    Sin @pattern: es un cálculo directo de la demanda.
    """

    def __init__(self, sectors: Sequence[SectorSpec], demand: DemandSpec) -> None:
        self._sectors = list(sectors)
        self._demand = demand
        weights = np.array(demand.hourly_weights, dtype=np.float64)
        self._profile: npt.NDArray[np.float64] = weights / weights.sum()

    def residents(self, rng: np.random.Generator) -> dict[str, int]:
        """Personas por sector: suma del sorteo de personas de cada hogar."""
        residents: dict[str, int] = {}
        for sector in self._sectors:
            per_household = rng.integers(
                self._demand.persons_min, self._demand.persons_max + 1, size=sector.households
            )
            residents[sector.id] = int(per_household.sum())
        return residents

    def daily_volume_m3(self, residents: int) -> float:
        """Volumen diario de un sector con esas personas, en m³."""
        liters = residents * self._demand.liters_per_person_per_day
        return liters / LITERS_PER_CUBIC_METER

    def hourly_demand_m3(
        self, days: int, rng: np.random.Generator
    ) -> dict[str, npt.NDArray[np.float64]]:
        """Demanda horaria de cada sector durante `days` días, en m³ por hora."""
        residents = self.residents(rng)
        return {
            sector_id: np.tile(self._profile * self.daily_volume_m3(people), days)
            for sector_id, people in residents.items()
        }
