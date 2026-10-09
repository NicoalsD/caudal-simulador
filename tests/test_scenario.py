"""Scenario YAML validation tests."""

from pathlib import Path

import pytest

from caudal_sim.builder import load_scenario
from caudal_sim.scenario import Scenario, ScenarioError

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "scenarios"
NORMAL_YAML = SCENARIOS_DIR / "normal.yaml"
EXPECTED_GAUGE_MAX = 5.0


def _write_variant(tmp_path: Path, old: str, new: str) -> Path:
    """Copies normal.yaml changing a single fragment, to test a specific error."""
    text = NORMAL_YAML.read_text(encoding="utf-8")
    assert old in text, f"el fragmento {old!r} no está en normal.yaml"
    path = tmp_path / "variant.yaml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def test_normal_scenario_loads_with_its_gauge_rule() -> None:
    scenario = load_scenario(NORMAL_YAML)

    assert isinstance(scenario, Scenario)
    assert scenario.meta.simulated is True
    assert scenario.tank.gauge_max == EXPECTED_GAUGE_MAX


def test_gauge_minimum_must_be_below_maximum(tmp_path: Path) -> None:
    path = _write_variant(tmp_path, "gauge_min: 0.0", "gauge_min: 5.0")

    with pytest.raises(ScenarioError, match="gauge_min debe ser menor"):
        load_scenario(path)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = _write_variant(tmp_path, "area_m2: 12.0", "area_m2: 12.0\n  area_extra: 1")

    with pytest.raises(ScenarioError, match="Extra inputs are not permitted"):
        load_scenario(path)


def test_scenario_must_be_marked_as_simulated(tmp_path: Path) -> None:
    path = _write_variant(tmp_path, "simulated: true", "simulated: false")

    with pytest.raises(ScenarioError):
        load_scenario(path)


def test_unknown_timezone_is_rejected(tmp_path: Path) -> None:
    path = _write_variant(tmp_path, "America/Bogota", "Mars/Olympus")

    with pytest.raises(ScenarioError, match="zona horaria desconocida"):
        load_scenario(path)


def test_missing_file_raises_scenario_error(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError, match="no se puede leer"):
        load_scenario(tmp_path / "no-existe.yaml")


def test_invalid_yaml_raises_scenario_error(tmp_path: Path) -> None:
    path = tmp_path / "roto.yaml"
    path.write_text("meta: [sin cerrar", encoding="utf-8")

    with pytest.raises(ScenarioError, match="YAML inválido"):
        load_scenario(path)
