"""Pruebas de las fugas: frecuencia de Poisson, caudal y reporte de la comunidad."""

from pathlib import Path

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from caudal_sim.builder import ScenarioBuilder
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.leaks import DAYS_PER_MONTH, LeakProcess
from caudal_sim.scenario import LeakSpec

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
SEED_MAX = 2**32 - 1
LONG_RUN_DAYS = 3000
HIGH_RATE_PER_MONTH = 3.0
FREQUENCY_TOLERANCE_RATIO = 0.15
SIMULATED_DAYS = 60
FLOW_TOLERANCE = 1e-12


def _spec(**overrides: float | int) -> LeakSpec:
    scenario = ScenarioBuilder().from_yaml(NORMAL_YAML).build()
    values = scenario.leaks.model_dump()
    values.update(overrides)
    return LeakSpec.model_validate(values)


def test_yearly_leak_count_follows_the_monthly_rate() -> None:
    spec = _spec(rate_per_month=HIGH_RATE_PER_MONTH)

    run = LeakProcess(spec).simulate(LONG_RUN_DAYS, np.random.default_rng(2026))
    expected = HIGH_RATE_PER_MONTH / DAYS_PER_MONTH * LONG_RUN_DAYS

    assert abs(len(run.leaks) - expected) / expected < FREQUENCY_TOLERANCE_RATIO


def test_zero_rate_means_no_leaks() -> None:
    run = LeakProcess(_spec(rate_per_month=0.0)).simulate(SIMULATED_DAYS, np.random.default_rng(1))

    assert run.leaks == ()
    assert not run.outflow_m3_per_hour.any()


@settings(max_examples=100)
@given(seed=st.integers(min_value=0, max_value=SEED_MAX))
def test_outflow_equals_the_active_leaks_flow_every_hour(seed: int) -> None:
    spec = _spec(rate_per_month=HIGH_RATE_PER_MONTH)

    run = LeakProcess(spec).simulate(SIMULATED_DAYS, np.random.default_rng(seed))

    expected = np.zeros(SIMULATED_DAYS * HOURS_PER_DAY)
    for leak in run.leaks:
        expected[leak.start_day * HOURS_PER_DAY : leak.repair_day * HOURS_PER_DAY] += (
            leak.flow_m3_per_hour
        )
    np.testing.assert_allclose(run.outflow_m3_per_hour, expected, atol=FLOW_TOLERANCE)


@settings(max_examples=100)
@given(seed=st.integers(min_value=0, max_value=SEED_MAX))
def test_reports_happen_only_while_the_leak_is_open(seed: int) -> None:
    spec = _spec(rate_per_month=HIGH_RATE_PER_MONTH)

    run = LeakProcess(spec).simulate(SIMULATED_DAYS, np.random.default_rng(seed))

    for leak in run.leaks:
        if leak.reported_day is not None:
            assert leak.start_day <= leak.reported_day < leak.repair_day


def test_same_seed_gives_the_same_leaks() -> None:
    process = LeakProcess(_spec(rate_per_month=HIGH_RATE_PER_MONTH))

    first = process.simulate(SIMULATED_DAYS, np.random.default_rng(4))
    second = process.simulate(SIMULATED_DAYS, np.random.default_rng(4))

    assert first.leaks == second.leaks
    np.testing.assert_array_equal(first.outflow_m3_per_hour, second.outflow_m3_per_hour)
