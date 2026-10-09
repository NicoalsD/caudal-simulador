"""The scenario catalog: every scenario loads, and each variant moves its variable the right way."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from caudal_sim.builder import load_scenario
from caudal_sim.scenario import Scenario
from caudal_sim.terrain import SimulationRun, run_simulation

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
CATALOG = ("normal-year", "dry-year", "rainy-year", "frequent-leaks", "presentation")
YEAR_DAYS = 365
SEED = 42


def _scenario(name: str) -> Scenario:
    return load_scenario(SCENARIOS / f"{name}.yaml")


def _year(name: str) -> SimulationRun:
    return run_simulation(_scenario(name), YEAR_DAYS, SEED)


@pytest.mark.parametrize("name", CATALOG)
def test_every_scenario_loads_and_declares_its_devices(name: str) -> None:
    scenario = _scenario(name)

    assert scenario.meta.name == name
    assert scenario.meta.simulated is True
    assert scenario.devices.valve.max_travel_seconds >= scenario.devices.valve.travel_seconds


def test_dry_year_rains_less_than_the_normal_year() -> None:
    dry = float(np.sum(_year("dry-year").truth.daily_rain_mm))
    normal = float(np.sum(_year("normal-year").truth.daily_rain_mm))

    assert dry < normal


def test_rainy_year_rains_more_than_the_normal_year() -> None:
    rainy = float(np.sum(_year("rainy-year").truth.daily_rain_mm))
    normal = float(np.sum(_year("normal-year").truth.daily_rain_mm))

    assert rainy > normal


def test_frequent_leaks_produce_more_leaks_than_the_normal_year() -> None:
    frequent = len(_year("frequent-leaks").truth.leaks)
    normal = len(_year("normal-year").truth.leaks)

    assert frequent > normal
