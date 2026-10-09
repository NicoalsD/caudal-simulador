"""Regression test of the normal scenario: the tank drains and overflows now and then."""

from pathlib import Path

import numpy as np

from caudal_sim.builder import load_scenario
from caudal_sim.terrain import run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
YEAR_DAYS = 365
SEED = 42
MAX_OVERFLOW_HOUR_FRACTION = 0.10
LOW_LEVEL_PERCENTILE = 5
MEDIAN_PERCENTILE = 50
LOW_LEVEL_M = 1.0
MEDIAN_MARGIN_M = 1.0


def test_normal_year_drains_and_overflows_only_now_and_then() -> None:
    scenario = load_scenario(NORMAL_YAML)

    truth = run_simulation(scenario, YEAR_DAYS, SEED).truth

    overflow_fraction = float(np.mean(truth.overflow_m3_per_hour > 0.0))
    assert overflow_fraction < MAX_OVERFLOW_HOUR_FRACTION


def test_normal_year_visits_the_low_levels_and_stays_below_the_top() -> None:
    scenario = load_scenario(NORMAL_YAML)

    truth = run_simulation(scenario, YEAR_DAYS, SEED).truth

    low = float(np.percentile(truth.level_m_per_hour, LOW_LEVEL_PERCENTILE))
    median = float(np.percentile(truth.level_m_per_hour, MEDIAN_PERCENTILE))
    assert low < LOW_LEVEL_M
    assert median < scenario.tank.gauge_max - MEDIAN_MARGIN_M
