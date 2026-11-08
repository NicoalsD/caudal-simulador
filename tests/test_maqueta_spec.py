"""The maqueta scenario file: it loads, and the model rules reject inconsistent values."""

from pathlib import Path

import pytest

from caudal_sim.maqueta_spec import MaquetaSpecError, load_maqueta_spec

SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "maqueta.yaml"
OUTLET_COUNT = 2
BASE = """
meta: {name: maqueta, description: prueba, simulated: true}
tank: {area_m2: 0.07, height_m: 0.35, overflow_m: 0.32, initial_level_m: 0.10,
       float_high_m: 0.30, float_restart_m: 0.26}
pump: {flow_l_per_min: 4.0}
outlets:
  - {name: Salida 1, diameter_in: 0.25, discharge_coefficient: 0.6}
  - {name: Salida 2, diameter_in: 0.25, discharge_coefficient: 0.6}
valve: {travel_seconds: 3, max_travel_seconds: 6}
timing: {tick_seconds: 1.0, telemetry_interval_seconds: 10, command_poll_seconds: 2}
buffer: {capacity_batches: 500, max_attempts: 5}
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "maqueta.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_shipped_scenario_has_the_geometry_of_the_maqueta() -> None:
    spec = load_maqueta_spec(SCENARIO)

    assert spec.meta.simulated is True
    assert spec.tank.area_m2 == pytest.approx(0.07)
    assert spec.tank.height_m == pytest.approx(0.35)
    assert spec.tank.overflow_m == pytest.approx(0.32)
    assert spec.pump.flow_l_per_min == pytest.approx(4.0)
    assert len(spec.outlets) == OUTLET_COUNT
    assert all(outlet.diameter_in == pytest.approx(0.25) for outlet in spec.outlets)
    assert all(outlet.discharge_coefficient == pytest.approx(0.6) for outlet in spec.outlets)


def test_the_base_text_is_a_valid_scenario(tmp_path: Path) -> None:
    assert load_maqueta_spec(_write(tmp_path, BASE)).tank.overflow_m == pytest.approx(0.32)


def test_overflow_above_the_tank_height_is_rejected(tmp_path: Path) -> None:
    text = BASE.replace("overflow_m: 0.32", "overflow_m: 0.40")

    with pytest.raises(MaquetaSpecError, match="rebose"):
        load_maqueta_spec(_write(tmp_path, text))


def test_the_pump_must_restart_below_the_float(tmp_path: Path) -> None:
    text = BASE.replace("float_restart_m: 0.26", "float_restart_m: 0.31")

    with pytest.raises(MaquetaSpecError, match="arranque"):
        load_maqueta_spec(_write(tmp_path, text))


def test_the_maqueta_has_exactly_two_outlets(tmp_path: Path) -> None:
    lines = BASE.splitlines()
    text = "\n".join(line for line in lines if "Salida 2" not in line)

    with pytest.raises(MaquetaSpecError, match="outlets"):
        load_maqueta_spec(_write(tmp_path, text))


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    text = BASE.replace("pump: {flow_l_per_min: 4.0}", "pump: {flow_l_per_min: 4.0, extra: 1}")

    with pytest.raises(MaquetaSpecError):
        load_maqueta_spec(_write(tmp_path, text))


def test_a_missing_file_is_a_spanish_error(tmp_path: Path) -> None:
    with pytest.raises(MaquetaSpecError, match="No se pudo leer"):
        load_maqueta_spec(tmp_path / "no-existe.yaml")
