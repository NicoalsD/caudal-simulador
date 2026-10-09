"""Full-run reproducibility tests.

Covers pattern P01 (Singleton): the single clock is reconfigured between runs of the same
process without leaving state. Comparisons are between runs, not against golden hashes,
because a numpy or pyarrow version change must not break the test.
"""

import hashlib
from pathlib import Path

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from caudal_sim.builder import ScenarioBuilder, load_scenario
from caudal_sim.clock import SimulationClock
from caudal_sim.export import export_run
from caudal_sim.terrain import SimulationRun, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
SEED_MAX = 2**32 - 1
RUN_DAYS = 10
PROPERTY_DAYS = 2


def _hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _run(seed: int, days: int = RUN_DAYS) -> SimulationRun:
    return run_simulation(load_scenario(NORMAL_YAML), days, seed)


def test_same_seed_in_the_same_process_exports_identical_files(tmp_path: Path) -> None:
    first = export_run(_run(42), tmp_path / "primera")
    second = export_run(_run(42), tmp_path / "segunda")

    assert _hashes(first.parent) == _hashes(second.parent)


def test_a_fresh_clock_does_not_change_the_result(tmp_path: Path) -> None:
    first = export_run(_run(42), tmp_path / "con-reloj")
    SimulationClock._instance = None
    second = export_run(_run(42), tmp_path / "reloj-nuevo")

    assert _hashes(first.parent) == _hashes(second.parent)


def test_a_different_seed_changes_the_data(tmp_path: Path) -> None:
    first = export_run(_run(42), tmp_path / "semilla-42")
    other = export_run(_run(43), tmp_path / "semilla-43")

    assert (
        _hashes(first.parent)["observed/readings.csv"]
        != _hashes(other.parent)["observed/readings.csv"]
    )


@settings(max_examples=20, deadline=None)
@given(seed=st.integers(min_value=0, max_value=SEED_MAX))
def test_runs_with_the_same_seed_match_array_by_array(seed: int) -> None:
    first = _run(seed, PROPERTY_DAYS)
    second = _run(seed, PROPERTY_DAYS)

    np.testing.assert_array_equal(first.truth.level_m_per_hour, second.truth.level_m_per_hour)
    np.testing.assert_array_equal(first.truth.daily_rain_mm, second.truth.daily_rain_mm)
    assert first.observed == second.observed


def test_changing_leaks_does_not_change_the_rain() -> None:
    base = load_scenario(NORMAL_YAML)
    changed = ScenarioBuilder().from_yaml(NORMAL_YAML).override("leaks.rate_per_month", 4.0).build()

    rain_base = run_simulation(base, RUN_DAYS, 42).truth.daily_rain_mm
    rain_changed = run_simulation(changed, RUN_DAYS, 42).truth.daily_rain_mm

    np.testing.assert_array_equal(rain_base, rain_changed)
