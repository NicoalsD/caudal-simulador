"""Backtest windows: window geometry, template method order, and manifests per dataset."""

import json
from pathlib import Path
from typing import Any

import pandas as pd

from caudal_sim.backtest import (
    BACKTEST_MANIFEST_NAME,
    HORIZON_HOURS,
    INPUT_HOURS,
    INPUTS_FOLDER,
    TARGETS_FOLDER,
    BacktestExporter,
    ObservedInputsExporter,
    TruthTargetsExporter,
    WindowSpec,
    export_backtest_windows,
    windows_for,
)
from caudal_sim.builder import load_scenario
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.export import Format
from caudal_sim.terrain import SimulationRun, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
SIMULATED_DAYS = 12
SEED = 4


def _run() -> SimulationRun:
    return run_simulation(load_scenario(NORMAL_YAML), SIMULATED_DAYS, SEED)


def test_windows_fit_inside_the_simulated_days() -> None:
    windows = windows_for(SIMULATED_DAYS)

    assert windows
    for window in windows:
        assert window.input_start_hour >= 0
        assert window.horizon_end_hour <= SIMULATED_DAYS * HOURS_PER_DAY
        assert window.horizon_start_hour == window.input_end_hour


def test_no_windows_when_the_run_is_shorter_than_one_window() -> None:
    assert windows_for(1) == ()


def test_window_spans_have_the_configured_length() -> None:
    window = windows_for(SIMULATED_DAYS)[0]

    assert window.input_end_hour - window.input_start_hour == INPUT_HOURS
    assert window.horizon_end_hour - window.horizon_start_hour == HORIZON_HOURS


def test_each_dataset_has_its_own_folder_and_manifest(tmp_path: Path) -> None:
    inputs_manifest, targets_manifest = export_backtest_windows(_run(), tmp_path)

    assert inputs_manifest.parent.name == INPUTS_FOLDER
    assert targets_manifest.parent.name == TARGETS_FOLDER
    assert inputs_manifest.name == BACKTEST_MANIFEST_NAME
    assert (inputs_manifest.parent / "windows.csv").exists()
    assert (targets_manifest.parent / "windows.parquet").exists()


def test_manifests_declare_source_and_truth_flag(tmp_path: Path) -> None:
    inputs_manifest, targets_manifest = export_backtest_windows(_run(), tmp_path)

    inputs = json.loads(inputs_manifest.read_text(encoding="utf-8"))
    targets = json.loads(targets_manifest.read_text(encoding="utf-8"))
    assert inputs["source"] == "observed"
    assert inputs["truth_included"] is False
    assert targets["source"] == "truth"
    assert targets["truth_included"] is True
    assert inputs["window_count"] == len(windows_for(SIMULATED_DAYS))


def test_target_rows_cover_each_horizon_hour_of_each_window(tmp_path: Path) -> None:
    run = _run()
    windows = windows_for(run.days)

    table = TruthTargetsExporter().build_table(run, windows)

    assert len(table) == len(windows) * HORIZON_HOURS


class _SpyExporter(BacktestExporter):
    folder = "spy"
    source_label = "observed"
    truth_included = False

    def __init__(self) -> None:
        self.calls: list[str] = []

    def build_table(self, run: SimulationRun, windows: tuple[WindowSpec, ...]) -> pd.DataFrame:
        self.calls.append("build_table")
        return pd.DataFrame({"window_id": []})

    def _write_files(
        self, table: pd.DataFrame, target: Path, formats: tuple[Format, ...], out_dir: Path
    ) -> dict[str, dict[str, Any]]:
        self.calls.append("write_files")
        return super()._write_files(table, target, formats, out_dir)

    def _write_manifest(
        self,
        run: SimulationRun,
        windows: tuple[WindowSpec, ...],
        target: Path,
        formats: tuple[Format, ...],
        written: dict[str, dict[str, Any]],
    ) -> Path:
        self.calls.append("write_manifest")
        return super()._write_manifest(run, windows, target, formats, written)


def test_template_method_runs_the_steps_in_a_fixed_order(tmp_path: Path) -> None:
    spy = _SpyExporter()

    spy.export(_run(), tmp_path, ("csv",))

    assert spy.calls == ["build_table", "write_files", "write_manifest"]


def test_both_concrete_exporters_extend_the_template() -> None:
    assert issubclass(ObservedInputsExporter, BacktestExporter)
    assert issubclass(TruthTargetsExporter, BacktestExporter)
    assert ObservedInputsExporter.export is TruthTargetsExporter.export
