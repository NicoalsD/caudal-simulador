"""Export tests: files, manifest with hashes and byte-level reproducibility."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from caudal_sim.builder import load_scenario
from caudal_sim.export import FORMATS, MANIFEST_NAME, export_run
from caudal_sim.terrain import SimulationRun, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
SIMULATED_DAYS = 5
SEED = 7


def _run() -> SimulationRun:
    return run_simulation(load_scenario(NORMAL_YAML), SIMULATED_DAYS, SEED)


def test_export_writes_observed_and_truth_in_both_formats(tmp_path: Path) -> None:
    export_run(_run(), tmp_path)

    for folder in ("observed", "truth"):
        assert list((tmp_path / folder).glob("*.csv"))
        assert list((tmp_path / folder).glob("*.parquet"))


def test_manifest_declares_simulated_data_and_the_seed(tmp_path: Path) -> None:
    manifest_path = export_run(_run(), tmp_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest_path.name == MANIFEST_NAME
    assert manifest["is_simulated"] is True
    assert manifest["seed"] == SEED
    assert manifest["formats"] == list(FORMATS)
    assert "generated_at" not in manifest


def test_manifest_hashes_match_the_files(tmp_path: Path) -> None:
    manifest = json.loads(export_run(_run(), tmp_path).read_text(encoding="utf-8"))

    for relative, info in manifest["files"].items():
        digest = hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest()
        assert digest == info["sha256"], relative


def test_same_run_exports_identical_bytes(tmp_path: Path) -> None:
    first = export_run(_run(), tmp_path / "a")
    second = export_run(_run(), tmp_path / "b")

    assert first.read_bytes() == second.read_bytes()


def test_observed_csv_has_no_truth_columns(tmp_path: Path) -> None:
    export_run(_run(), tmp_path)

    for path in (tmp_path / "observed").glob("*.csv"):
        header = pd.read_csv(path, nrows=0).columns
        for column in header:
            assert "level" not in column
            assert "volume" not in column
            assert "leak" not in column
            assert "requested" not in column


def test_readings_csv_has_one_row_per_arrival(tmp_path: Path) -> None:
    run = _run()
    export_run(run, tmp_path)

    frame = pd.read_csv(tmp_path / "observed" / "readings.csv")

    assert len(frame) == len(run.observed.readings)
