"""Tests of the `generate` CLI command."""

import json
from pathlib import Path

from typer.testing import CliRunner

from caudal_sim.cli import app

runner = CliRunner()
NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
SMOKE_DAYS = "3"
SEED = "11"
SUCCESS = 0
SCENARIO_ERROR = 1
USAGE_ERROR = 2


def test_generate_writes_the_dataset_and_its_manifest(tmp_path: Path) -> None:
    out = tmp_path / "salida"

    result = runner.invoke(
        app,
        [
            "generate",
            "--scenario",
            str(NORMAL_YAML),
            "--days",
            SMOKE_DAYS,
            "--seed",
            SEED,
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == SUCCESS, result.output
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == int(SEED)
    assert manifest["is_simulated"] is True
    assert "Datos simulados" in result.output


def test_format_option_limits_the_files_written(tmp_path: Path) -> None:
    out = tmp_path / "solo-csv"

    result = runner.invoke(
        app,
        [
            "generate",
            "--scenario",
            str(NORMAL_YAML),
            "--days",
            SMOKE_DAYS,
            "--out",
            str(out),
            "--format",
            "csv",
        ],
    )

    assert result.exit_code == SUCCESS, result.output
    assert not list(out.rglob("*.parquet"))
    assert list((out / "observed").glob("*.csv"))


def test_unknown_scenario_prints_a_spanish_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["generate", "--scenario", "no-existe", "--days", SMOKE_DAYS, "--out", str(tmp_path)],
    )

    assert result.exit_code == SCENARIO_ERROR
    assert "no se puede leer el escenario" in result.output


def test_zero_days_is_rejected_by_the_option_parser(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["generate", "--scenario", str(NORMAL_YAML), "--days", "0", "--out", str(tmp_path)],
    )

    assert result.exit_code == USAGE_ERROR
