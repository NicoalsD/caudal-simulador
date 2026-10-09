"""Local dashboard API: state, Swagger in Spanish, loopback default, no shared origins."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from caudal_sim import cli
from caudal_sim.config import DEFAULT_DASHBOARD_HOST, DashboardSettings
from caudal_sim.dashboard_api import API_TITLE, STATE_PATH, create_dashboard_app
from caudal_sim.dashboard_session import DashboardSession
from caudal_sim.event_bus import SimulationEvent, SimulationEventKind

SCENARIO = "normal-year"
VALVE_ID = "0190f3a2-7000-7000-8000-000000000001"
VALVE_LABEL = "Sector Alto"
AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
HTTP_OK = 200
TANK_LEVEL_M = 3.4
SENSOR_LEVEL_M = 3.41
GAUGE_MIN_M = 0.0
GAUGE_MAX_M = 5.0
ALLOWED_STATE_KEYS = {
    "scenario",
    "simulated",
    "notice",
    "updated_at",
    "tank_level_m",
    "sensor_level_m",
    "gauge_min_m",
    "gauge_max_m",
    "paused",
    "speed_factor",
    "valves",
}


def _client(session: DashboardSession) -> TestClient:
    return TestClient(create_dashboard_app(session))


def _session() -> DashboardSession:
    session = DashboardSession(scenario=SCENARIO)
    session.register_valve(VALVE_ID, VALVE_LABEL)
    session.set_levels(AT, TANK_LEVEL_M, SENSOR_LEVEL_M)
    session.set_gauge_rule(GAUGE_MIN_M, GAUGE_MAX_M)
    return session


def test_state_reports_simulated_levels_and_valves() -> None:
    response = _client(_session()).get(STATE_PATH)

    assert response.status_code == HTTP_OK
    body: dict[str, Any] = response.json()
    assert set(body) == ALLOWED_STATE_KEYS
    assert body["simulated"] is True
    assert body["notice"] == "Datos simulados"
    assert body["scenario"] == SCENARIO
    assert body["tank_level_m"] == TANK_LEVEL_M
    assert body["sensor_level_m"] == SENSOR_LEVEL_M
    assert body["gauge_min_m"] == GAUGE_MIN_M
    assert body["gauge_max_m"] == GAUGE_MAX_M
    assert body["valves"] == [{"id": VALVE_ID, "label": VALVE_LABEL, "status": "CLOSED"}]


def test_valve_event_on_the_bus_updates_the_state() -> None:
    session = _session()
    event = SimulationEvent(
        occurred_at=AT,
        kind=SimulationEventKind.VALVE_STATE_CHANGED,
        subject_id=VALVE_ID,
        detail="OPEN",
    )

    session.bus.publish(event)

    assert _client(session).get(STATE_PATH).json()["valves"][0]["status"] == "OPEN"


def test_events_of_other_kinds_leave_the_valves_as_they_are() -> None:
    session = _session()

    session.bus.publish(
        SimulationEvent(
            occurred_at=AT,
            kind=SimulationEventKind.COMMAND_DELIVERED,
            subject_id=VALVE_ID,
            detail="OPEN",
        )
    )

    assert session.snapshot().valves[0].status == "CLOSED"


def test_swagger_is_in_spanish_and_served_at_docs() -> None:
    client = _client(_session())

    schema = client.get("/openapi.json").json()
    docs = client.get("/docs")

    assert schema["info"]["title"] == API_TITLE
    assert "Estado actual de la simulación" in str(schema)
    assert docs.status_code == HTTP_OK


def test_api_sends_no_cors_headers_to_other_origins() -> None:
    response = _client(_session()).get(STATE_PATH, headers={"Origin": "https://ejemplo.invalido"})

    assert "access-control-allow-origin" not in response.headers


def test_dashboard_listens_on_loopback_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAUDAL_SIM_DASHBOARD_HOST", raising=False)

    assert DashboardSettings().host == DEFAULT_DASHBOARD_HOST == "127.0.0.1"


def test_tablero_command_warns_when_it_is_exposed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAUDAL_SIM_DASHBOARD_HOST", raising=False)
    served: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        served.update(kwargs)

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    runner = CliRunner()

    default = runner.invoke(cli.app, ["tablero"])

    assert default.exit_code == 0
    assert served["host"] == "127.0.0.1"
    assert "fuera de este equipo" not in default.output

    exposed = runner.invoke(cli.app, ["tablero", "--host", "0.0.0.0"])

    assert exposed.exit_code == 0
    assert served["host"] == "0.0.0.0"
    assert "fuera de este equipo" in exposed.output


def test_built_dashboard_is_served_from_the_same_origin_and_api_wins(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><title>Tablero</title>", encoding="utf-8")
    client = TestClient(create_dashboard_app(_session(), static_dir=tmp_path))

    page = client.get("/")
    state = client.get(STATE_PATH)

    assert page.status_code == HTTP_OK
    assert "Tablero" in page.text
    assert state.json()["simulated"] is True
