"""Device parameters come from the scenario YAML and are validated by Pydantic."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from caudal_sim.builder import ScenarioBuilder, load_scenario
from caudal_sim.device_kit import FieldKitFactory
from caudal_sim.offline_buffer import BufferFullError, OfflineBufferTransport
from caudal_sim.scenario import ScenarioError
from caudal_sim.telemetry_transport import TelemetryRequest, TransportUnavailableError
from caudal_sim.valve_state import ValveStatus

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
START = datetime(2026, 1, 1, tzinfo=UTC)
TANK_LEVEL_M = 3.4
TRAVEL_SECONDS = 15.0
MAX_TRAVEL_SECONDS = 60.0
CAPACITY = 500
MAX_ATTEMPTS = 5


class _DownSubject:
    """Network that never answers: every send is unavailable."""

    def send(self, request: TelemetryRequest) -> None:
        raise TransportUnavailableError("sin red")


def _tank_level(_at: datetime) -> float:
    return TANK_LEVEL_M


def test_normal_scenario_declares_every_device_parameter() -> None:
    devices = load_scenario(NORMAL_YAML).devices

    assert devices.valve.travel_seconds == TRAVEL_SECONDS
    assert devices.valve.max_travel_seconds == MAX_TRAVEL_SECONDS
    assert devices.buffer.capacity_batches == CAPACITY
    assert devices.buffer.max_attempts == MAX_ATTEMPTS
    assert devices.sensor.stuck_until_hour > devices.sensor.stuck_from_hour


def test_valve_travel_time_of_the_kit_comes_from_the_scenario() -> None:
    devices = load_scenario(NORMAL_YAML).devices
    factory = FieldKitFactory.from_spec(
        devices, tank_level=_tank_level, start=START, rng=np.random.default_rng(0)
    )
    actuator = factory.create_kit().actuator

    actuator.request_open()
    actuator.advance(timedelta(seconds=TRAVEL_SECONDS - 1))
    assert actuator.status is ValveStatus.OPENING
    actuator.advance(timedelta(seconds=1))
    assert actuator.status is ValveStatus.OPEN


def test_buffer_capacity_and_attempts_come_from_the_scenario() -> None:
    devices = load_scenario(NORMAL_YAML).devices
    sleeps: list[float] = []
    proxy = OfflineBufferTransport.from_spec(_DownSubject(), devices.buffer, sleeper=sleeps.append)
    request = TelemetryRequest("/api/v1/devices/telemetry", b"{}")

    for _ in range(CAPACITY):
        proxy.send(request)
    with pytest.raises(BufferFullError):
        proxy.send(request)
    assert proxy.pending == CAPACITY

    assert proxy.drain() == 0
    assert len(sleeps) == MAX_ATTEMPTS - 1


def _variant(tmp_path: Path, old: str, new: str) -> Path:
    text = NORMAL_YAML.read_text(encoding="utf-8")
    assert old in text, f"el fragmento {old!r} no está en normal-year.yaml"
    path = tmp_path / "variant.yaml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


def test_max_travel_cannot_be_shorter_than_the_travel(tmp_path: Path) -> None:
    path = _variant(tmp_path, "max_travel_seconds: 60", "max_travel_seconds: 10")

    with pytest.raises(ScenarioError, match="max_travel_seconds no puede ser menor"):
        load_scenario(path)


def test_stuck_window_must_end_after_it_starts(tmp_path: Path) -> None:
    path = _variant(tmp_path, "stuck_until_hour: 1012", "stuck_until_hour: 1000")

    with pytest.raises(ScenarioError, match="stuck_until_hour debe ser mayor"):
        load_scenario(path)


def test_buffer_needs_at_least_one_attempt(tmp_path: Path) -> None:
    path = _variant(tmp_path, "max_attempts: 5", "max_attempts: 0")

    with pytest.raises(ScenarioError, match="max_attempts"):
        load_scenario(path)


def test_device_section_rejects_unknown_keys(tmp_path: Path) -> None:
    path = _variant(tmp_path, "capacity_batches: 500", "capacity_batches: 500\n    capacidad: 1")

    with pytest.raises(ScenarioError, match="capacidad"):
        load_scenario(path)


def test_devices_section_is_required(tmp_path: Path) -> None:
    text = NORMAL_YAML.read_text(encoding="utf-8")
    path = tmp_path / "no-devices.yaml"
    path.write_text(text.split("\ndevices:")[0] + "\n", encoding="utf-8")

    with pytest.raises(ScenarioError, match="devices"):
        ScenarioBuilder().from_yaml(path).build()
