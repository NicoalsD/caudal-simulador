"""Period consistency of exports: every date falls inside the period in the manifest."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from caudal_sim.builder import load_scenario
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.export import export_run
from caudal_sim.minutes_export import ACTAS_TABLE, export_confirmed_executions
from caudal_sim.terrain import run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
SEED = 13


@pytest.mark.parametrize("days", [1, 4])
def test_actas_dates_lie_inside_the_declared_period(tmp_path: Path, days: int) -> None:
    run = run_simulation(load_scenario(NORMAL_YAML), days, SEED)
    manifest = json.loads(export_confirmed_executions(run, tmp_path).read_text(encoding="utf-8"))
    frame = pd.read_csv(tmp_path / "actas" / f"{ACTAS_TABLE}.csv")

    start = date.fromisoformat(manifest["period"]["start"])
    end = date.fromisoformat(manifest["period"]["end"])
    dates = pd.to_datetime(frame["service_date"]).dt.date
    assert manifest["period"]["days"] == days
    assert (dates >= start).all()
    assert (dates <= end).all()
    assert (frame["day_index"] < days).all()
    assert (frame["day_index"] >= 0).all()


def test_service_date_matches_day_index_and_start_date(tmp_path: Path) -> None:
    run = run_simulation(load_scenario(NORMAL_YAML), 3, SEED)
    export_confirmed_executions(run, tmp_path)
    frame = pd.read_csv(tmp_path / "actas" / f"{ACTAS_TABLE}.csv")

    for _, row in frame.iterrows():
        expected = (run.start + timedelta(days=int(row["day_index"]))).date()
        assert date.fromisoformat(str(row["service_date"])) == expected


def test_shift_windows_are_forward_and_inside_the_day(tmp_path: Path) -> None:
    run = run_simulation(load_scenario(NORMAL_YAML), 3, SEED)
    export_confirmed_executions(run, tmp_path)
    frame = pd.read_csv(tmp_path / "actas" / f"{ACTAS_TABLE}.csv")

    assert (frame["start_hour"] < frame["end_hour"]).all()
    assert (frame["start_hour"] >= 0).all()
    assert (frame["end_hour"] <= HOURS_PER_DAY).all()


def test_observed_timestamps_stay_inside_the_simulated_period(tmp_path: Path) -> None:
    days = 2
    run = run_simulation(load_scenario(NORMAL_YAML), days, SEED)
    export_run(run, tmp_path)
    readings = pd.read_csv(tmp_path / "observed" / "readings.csv")

    first = run.start
    last_exclusive = run.start + timedelta(days=days)
    stamps = [datetime.fromisoformat(value) for value in readings["observed_at"]]
    assert stamps
    assert all(first <= stamp < last_exclusive for stamp in stamps)
