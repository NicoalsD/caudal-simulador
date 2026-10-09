"""Property tests of the demo script: for any seed, the faults come in order and repeat exactly."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from caudal_sim.builder import load_scenario
from caudal_sim.demo import _leak_report_hours
from caudal_sim.terrain import run_simulation
from test_demo import (
    DEMO_DAYS,
    GAUGE_ERROR_CHECK,
    LEAK_CHECK,
    MUDDY_CHECK,
    SILENT_CHECK,
    _run_demo,
)

PRESENTATION_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "presentation.yaml"
MAX_SEED = 2**32 - 1
MAX_EXAMPLES = 15
CORRECTED_CHECK = "Lectura corregida"
MANUAL_STEPS = 4


def _steps(seed: int) -> list[str]:
    director, _ = _run_demo(seed_override=seed)
    return [check.step for check in director.checks()]


@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(seed=st.integers(min_value=0, max_value=MAX_SEED))
def test_for_any_seed_the_faults_come_in_script_order(seed: int) -> None:
    scenario = load_scenario(PRESENTATION_YAML)
    run = run_simulation(scenario, DEMO_DAYS, seed)
    assert scenario.demo is not None
    leak_reports = len(_leak_report_hours(run, scenario.demo.damage_report_hour_of_day))

    steps = _steps(seed)

    # The script runs by hour: the gauge error, its correction and the muddy note come first,
    # then the silent sensor (hour 12 in the scenario), and the reported leak last (hour 63).
    expected = [GAUGE_ERROR_CHECK, CORRECTED_CHECK, MUDDY_CHECK, SILENT_CHECK]
    expected += [LEAK_CHECK] * leak_reports
    assert steps[: len(expected)] == expected
    assert len(steps) == len(expected) + MANUAL_STEPS


@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(seed=st.integers(min_value=0, max_value=MAX_SEED))
def test_the_same_seed_gives_the_same_checklist_and_requests(seed: int) -> None:
    first_director, first_requests = _run_demo(seed_override=seed)
    second_director, second_requests = _run_demo(seed_override=seed)

    assert first_director.checks() == second_director.checks()
    assert first_requests == second_requests


@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(seed=st.integers(min_value=0, max_value=MAX_SEED))
def test_the_gauge_error_is_always_refused_and_its_correction_accepted(seed: int) -> None:
    director, _ = _run_demo(seed_override=seed)
    checks = {check.step: check for check in director.checks()}

    assert checks[GAUGE_ERROR_CHECK].passed is True
    assert checks[CORRECTED_CHECK].passed is True
