"""Pruebas de los límites del tanque en corridas completas: regla, rebose y vaciado."""

from pathlib import Path

import numpy as np

from caudal_sim.builder import ScenarioBuilder
from caudal_sim.terrain import run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
LIMIT_DAYS = 120
STRONG_RAIN_GAIN = 50.0
HUGE_DEMAND_LITERS = 10_000
TOLERANCE_M = 1e-9


def _builder() -> ScenarioBuilder:
    return ScenarioBuilder().from_yaml(NORMAL_YAML)


def test_level_stays_inside_the_gauge_rule_for_a_normal_run() -> None:
    scenario = _builder().build()

    truth = run_simulation(scenario, LIMIT_DAYS, 42).truth

    assert np.all(truth.level_m_per_hour >= scenario.tank.gauge_min - TOLERANCE_M)
    assert np.all(truth.level_m_per_hour <= scenario.tank.gauge_max + TOLERANCE_M)
    assert np.all(truth.overflow_m3_per_hour >= 0.0)


def test_heavy_rain_overflows_and_pins_the_level_at_the_gauge_maximum() -> None:
    scenario = _builder().override("source.rain_gain_m3_per_hour_per_mm", STRONG_RAIN_GAIN).build()

    truth = run_simulation(scenario, LIMIT_DAYS, 42).truth

    assert truth.overflow_m3_per_hour.sum() > 0.0
    assert np.isclose(truth.level_m_per_hour.max(), scenario.tank.gauge_max)


def test_huge_demand_without_source_empties_the_tank_and_trims_the_delivery() -> None:
    scenario = (
        _builder()
        .override("source.base_flow_m3_per_hour", 0.0)
        .override("source.rain_gain_m3_per_hour_per_mm", 0.0)
        .override("demand.liters_per_person_per_day", HUGE_DEMAND_LITERS)
        .build()
    )

    truth = run_simulation(scenario, LIMIT_DAYS, 42).truth

    assert np.all(truth.level_m_per_hour >= -TOLERANCE_M)
    assert np.isclose(truth.level_m_per_hour.min(), 0.0, atol=TOLERANCE_M)
    assert np.any(truth.delivered_m3_per_hour < truth.requested_m3_per_hour - TOLERANCE_M)
