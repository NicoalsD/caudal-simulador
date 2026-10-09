"""Minutes export: confirmed executions, observed data only, with the period in the manifest."""

import json
from datetime import timedelta
from pathlib import Path

import pandas as pd

from caudal_sim.builder import load_scenario
from caudal_sim.minutes_export import ACTAS_MANIFEST_NAME, ACTAS_TABLE, export_confirmed_executions
from caudal_sim.terrain import SimulationRun, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
SIMULATED_DAYS = 5
SEED = 9


def _run() -> SimulationRun:
    return run_simulation(load_scenario(NORMAL_YAML), SIMULATED_DAYS, SEED)


def test_export_writes_one_row_per_confirmed_shift(tmp_path: Path) -> None:
    run = _run()
    manifest_path = export_confirmed_executions(run, tmp_path)

    frame = pd.read_csv(tmp_path / "actas" / f"{ACTAS_TABLE}.csv")
    assert len(frame) == len(run.observed.shift_executions)
    assert manifest_path.name == ACTAS_MANIFEST_NAME


def test_export_contains_no_ground_truth_columns(tmp_path: Path) -> None:
    export_confirmed_executions(_run(), tmp_path)

    columns = set(pd.read_csv(tmp_path / "actas" / f"{ACTAS_TABLE}.csv").columns)
    assert columns == {
        "day_index",
        "service_date",
        "sector_id",
        "start_hour",
        "end_hour",
        "outcome",
        "open_hours",
    }
    assert not {"level_m", "demand", "leak", "truth"} & set(columns)


def test_manifest_declares_observed_source_and_period(tmp_path: Path) -> None:
    run = _run()
    manifest = json.loads(export_confirmed_executions(run, tmp_path).read_text(encoding="utf-8"))

    assert manifest["is_simulated"] is True
    assert manifest["source"] == "observed"
    assert manifest["truth_included"] is False
    assert manifest["period"]["days"] == SIMULATED_DAYS
    assert manifest["period"]["start"] == run.start.date().isoformat()
    assert (
        manifest["period"]["end"]
        == (run.start.date() + timedelta(days=SIMULATED_DAYS - 1)).isoformat()
    )
