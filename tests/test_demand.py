"""Pruebas de la demanda horaria por sector."""

from pathlib import Path

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from caudal_sim.builder import load_scenario
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.demand import LITERS_PER_CUBIC_METER, SectorDemandModel

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
SEED_MAX = 2**32 - 1
SIMULATED_DAYS = 3
VOLUME_TOLERANCE_M3 = 1e-9
LITERS_TOLERANCE = 1e-6
PEAK_HOUR = 7
NIGHT_HOUR = 2


def _model() -> SectorDemandModel:
    scenario = load_scenario(NORMAL_YAML)
    return SectorDemandModel(scenario.sectors, scenario.demand)


def test_each_sector_has_one_series_with_one_value_per_hour() -> None:
    scenario = load_scenario(NORMAL_YAML)
    demand = _model().hourly_demand_m3(SIMULATED_DAYS, np.random.default_rng(1))

    assert set(demand) == {sector.id for sector in scenario.sectors}
    for series in demand.values():
        assert series.shape == (SIMULATED_DAYS * HOURS_PER_DAY,)


def test_morning_peak_asks_for_more_water_than_the_night() -> None:
    demand = _model().hourly_demand_m3(1, np.random.default_rng(1))

    for series in demand.values():
        assert series[PEAK_HOUR] > series[NIGHT_HOUR]


def test_residents_are_within_the_household_bounds() -> None:
    scenario = load_scenario(NORMAL_YAML)
    residents = _model().residents(np.random.default_rng(5))

    for sector in scenario.sectors:
        low = sector.households * scenario.demand.persons_min
        high = sector.households * scenario.demand.persons_max
        assert low <= residents[sector.id] <= high


@settings(max_examples=100)
@given(seed=st.integers(min_value=0, max_value=SEED_MAX))
def test_daily_volume_equals_residents_times_the_per_person_allowance(seed: int) -> None:
    scenario = load_scenario(NORMAL_YAML)
    model = _model()
    residents = model.residents(np.random.default_rng(seed))
    demand = model.hourly_demand_m3(1, np.random.default_rng(seed))

    for sector in scenario.sectors:
        expected = model.daily_volume_m3(residents[sector.id])
        assert abs(float(demand[sector.id].sum()) - expected) < VOLUME_TOLERANCE_M3
        expected_liters = residents[sector.id] * scenario.demand.liters_per_person_per_day
        assert abs(expected * LITERS_PER_CUBIC_METER - expected_liters) < LITERS_TOLERANCE


def test_same_seed_gives_the_same_residents() -> None:
    model = _model()

    assert model.residents(np.random.default_rng(9)) == model.residents(np.random.default_rng(9))
