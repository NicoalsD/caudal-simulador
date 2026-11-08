"""The `caudal-sim maqueta` command: configuration errors are reported in Spanish."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from caudal_sim.cli import EXIT_CONFIG_ERROR, app

SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "maqueta.yaml"
RUNNER = CliRunner()
ENV_NAMES = (
    "CAUDAL_SIM_MAQUETA_API_BASE_URL",
    "CAUDAL_SIM_MAQUETA_SENSOR_DEVICE_ID",
    "CAUDAL_SIM_MAQUETA_VALVE_1_DEVICE_ID",
    "CAUDAL_SIM_MAQUETA_VALVE_1_VALVE_ID",
    "CAUDAL_SIM_MAQUETA_VALVE_2_DEVICE_ID",
    "CAUDAL_SIM_MAQUETA_VALVE_2_VALVE_ID",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_command_is_listed_in_the_help() -> None:
    result = RUNNER.invoke(app, ["maqueta", "--help"])

    assert result.exit_code == 0
    assert "--scenario" in result.output
    assert "--api-url" in result.output


def test_a_missing_scenario_exits_with_a_configuration_error(clean_env: Path) -> None:
    result = RUNNER.invoke(app, ["maqueta", "--scenario", str(clean_env / "no.yaml")])

    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "No se pudo leer" in result.output


def test_a_bare_scenario_name_resolves_to_the_maqueta_file(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = SCENARIO.parents[1]
    monkeypatch.chdir(repo)

    result = RUNNER.invoke(app, ["maqueta", "--scenario", "maqueta"])

    # The file is found; the failure that follows is the missing identities, not the scenario.
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "No se pudo leer" not in result.output
    assert "CAUDAL_SIM_MAQUETA_SENSOR_DEVICE_ID" in result.output


def test_missing_identities_are_named_without_showing_any_secret(clean_env: Path) -> None:
    result = RUNNER.invoke(app, ["maqueta", "--scenario", str(SCENARIO)])

    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "CAUDAL_SIM_MAQUETA_SENSOR_DEVICE_ID" in result.output
    assert "BEGIN" not in result.output
