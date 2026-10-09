"""Separation between ground truth and forecast inputs in the backtest datasets."""

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd

from caudal_sim.backtest import (
    INPUT_HOURS,
    INPUTS_FOLDER,
    TARGETS_FOLDER,
    export_backtest_windows,
)
from caudal_sim.builder import load_scenario
from caudal_sim.terrain import SimulationRun, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
SIMULATED_DAYS = 12
SEED = 4
TRUTH_MARKERS = ("level", "inflow", "leak", "truth", "demand", "overflow", "rain")


def _run() -> SimulationRun:
    return run_simulation(load_scenario(NORMAL_YAML), SIMULATED_DAYS, SEED)


def _read(folder: Path) -> pd.DataFrame:
    return pd.read_csv(folder / "windows.csv")


def test_observed_inputs_carry_no_truth_columns(tmp_path: Path) -> None:
    export_backtest_windows(_run(), tmp_path)

    columns = list(_read(tmp_path / "backtest" / INPUTS_FOLDER).columns)
    assert columns == ["window_id", "hour_offset", "gauge_m", "is_delayed"]
    assert not [name for name in columns if any(marker in name for marker in TRUTH_MARKERS)]


def test_observed_inputs_do_not_depend_on_the_true_level(tmp_path: Path) -> None:
    run = _run()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    export_backtest_windows(run, first_dir)

    zeroed_truth = dataclasses.replace(
        run.truth,
        level_m_per_hour=np.zeros_like(run.truth.level_m_per_hour),
        inflow_m3_per_hour=np.zeros_like(run.truth.inflow_m3_per_hour),
    )
    export_backtest_windows(dataclasses.replace(run, truth=zeroed_truth), second_dir)

    first = (first_dir / "backtest" / INPUTS_FOLDER / "windows.csv").read_bytes()
    second = (second_dir / "backtest" / INPUTS_FOLDER / "windows.csv").read_bytes()
    assert first == second


def test_input_rows_never_reach_into_the_forecast_horizon(tmp_path: Path) -> None:
    export_backtest_windows(_run(), tmp_path)

    inputs = _read(tmp_path / "backtest" / INPUTS_FOLDER)
    assert (inputs["hour_offset"] >= 0).all()
    assert (inputs["hour_offset"] < INPUT_HOURS).all()


def test_targets_hold_the_truth_and_nothing_observed(tmp_path: Path) -> None:
    run = _run()
    export_backtest_windows(run, tmp_path)

    targets = _read(tmp_path / "backtest" / TARGETS_FOLDER)
    assert list(targets.columns) == ["window_id", "hour_offset", "level_m"]
    first = targets.iloc[0]
    expected = run.truth.level_m_per_hour[int(first["hour_offset"]) + 0 + INPUT_HOURS]
    assert np.isclose(first["level_m"], expected)


def test_each_dataset_declares_its_own_truth_flag(tmp_path: Path) -> None:
    inputs_manifest, targets_manifest = export_backtest_windows(_run(), tmp_path)

    assert 'truth_included": false' in inputs_manifest.read_text(encoding="utf-8")
    assert 'truth_included": true' in targets_manifest.read_text(encoding="utf-8")
    assert not (inputs_manifest.parent / "targets.csv").exists()
