"""Demo script: the five field faults, in order, through the API, with a checklist."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr
from typer.testing import CliRunner

from caudal_sim import cli
from caudal_sim.api_client import CaudalApiClient
from caudal_sim.api_payload import ApiPayloadAdapter, ImportContext
from caudal_sim.builder import load_scenario
from caudal_sim.dashboard_session import DashboardSession
from caudal_sim.demo import DemoDirector, _leak_report_hours
from caudal_sim.live import LiveOptions, LiveRunner, LiveWiring, NetworkGate
from caudal_sim.offline_buffer import OfflineBufferTransport
from caudal_sim.telemetry_transport import DeviceIdentity, SignedHttpTransport
from caudal_sim.terrain import run_simulation

ROOT = Path(__file__).resolve().parents[1]
PRESENTATION_YAML = ROOT / "scenarios" / "presentation.yaml"
NORMAL_YAML = ROOT / "scenarios" / "normal-year.yaml"
BASE = "https://api.test"
SLUG = "guaitarilla-demo"
TELEMETRY_URL = f"{BASE}/api/v1/devices/telemetry"
READINGS_URL = f"{BASE}/api/v1/readings"
LOGIN_URL = f"{BASE}/api/v1/auth/login"
REPORT_URL = f"{BASE}/api/v1/public/{SLUG}/damage-reports"
SCHEDULE_URL = f"{BASE}/api/v1/public/{SLUG}/schedule"
DEVICE_ID = UUID("0190f3a2-6666-7000-8000-000000000001")
AQUEDUCT_ID = UUID("0190f3a2-1111-7000-8000-000000000001")
TANK_ID = UUID("0190f3a2-2222-7000-8000-000000000001")
FIXED_NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
GAUGE_ERROR_VALUE = 8.0
DEMO_DAYS = 3
REPORT_HOUR = 63
TRACKING_CODE = "ABCD2345"
GAUGE_ERROR_CHECK = "Dato fuera de la regla"
MUDDY_CHECK = "Agua con barro"
LEAK_CHECK = "Fuga reportada"
SILENT_CHECK = "Sensor sin señal"
TRACKING_CHECK_TEXT = f"Código de seguimiento {TRACKING_CODE}"


def _reading_answer(request: httpx.Request) -> httpx.Response:
    body: dict[str, Any] = json.loads(request.content)
    if body["gauge_value"] == GAUGE_ERROR_VALUE:
        error = {"code": "GAUGE_OUT_OF_RANGE", "message": "Fuera de la regla del tanque."}
        return httpx.Response(422, json={"error": error})
    return httpx.Response(201, json={"reading": {"id": body["id"]}})


def _run_demo(*, seed_override: int | None = None) -> tuple[DemoDirector, dict[str, list[bytes]]]:
    scenario = load_scenario(PRESENTATION_YAML)
    run = run_simulation(scenario, DEMO_DAYS, seed_override or scenario.meta.default_seed)
    key = Ed25519PrivateKey.generate()
    session = DashboardSession(scenario=scenario.meta.name)
    api = CaudalApiClient(BASE, timeout_seconds=5.0)
    http = httpx.Client(base_url=BASE, timeout=5.0)
    gate = NetworkGate(SignedHttpTransport(http, DeviceIdentity(DEVICE_ID, key)))
    telemetry = OfflineBufferTransport.from_spec(
        gate, scenario.devices.buffer, sleeper=lambda _s: None
    )
    adapter = ApiPayloadAdapter(
        ImportContext(
            aqueduct_id=AQUEDUCT_ID,
            tank_id=TANK_ID,
            start=run.start,
            sector_slugs=tuple(sector.id for sector in scenario.sectors),
        )
    )
    captured: dict[str, list[bytes]] = {"readings": [], "reports": []}
    try:
        with respx.mock(assert_all_called=False) as mock:
            mock.post(LOGIN_URL).mock(return_value=httpx.Response(200, json={"access_token": "t"}))
            mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
            mock.get(SCHEDULE_URL).mock(
                return_value=httpx.Response(200, json={"aqueduct": {"is_demo": True}})
            )
            mock.post(READINGS_URL).mock(side_effect=_capture_readings(captured, _reading_answer))
            mock.post(REPORT_URL).mock(side_effect=_capture_reports(captured))
            api.login("operador.prueba", SecretStr("contraseña-de-prueba-larga"))
            wiring = LiveWiring(
                scenario=scenario,
                run=run,
                session=session,
                telemetry=telemetry,
                gate=gate,
                api=api,
                adapter=adapter,
                device_id=DEVICE_ID,
                tank_id=TANK_ID,
                sleeper=lambda _s: None,
            )
            assert scenario.demo is not None
            director = DemoDirector(scenario.demo, wiring, SLUG, now=lambda: FIXED_NOW)
            LiveRunner(wiring, LiveOptions(hour_seconds=0.0)).run(before_hour=director.before_hour)
    finally:
        api.close()
        http.close()
    return director, captured


def _capture_readings(
    captured: dict[str, list[bytes]], answer: Callable[[httpx.Request], httpx.Response]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["readings"].append(request.content)
        return answer(request)

    return handler


def _capture_reports(
    captured: dict[str, list[bytes]],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["reports"].append(request.content)
        return httpx.Response(201, json={"tracking_code": TRACKING_CODE, "status": "REPORTED"})

    return handler


def _by_step(director: DemoDirector) -> dict[str, Any]:
    return {check.step: check for check in director.checks()}


def test_the_five_faults_appear_in_the_checklist_with_their_outcome() -> None:
    director, _ = _run_demo()

    checks = _by_step(director)

    assert checks[GAUGE_ERROR_CHECK].passed is True
    assert checks[MUDDY_CHECK].passed is True
    assert checks[LEAK_CHECK].passed is True
    assert TRACKING_CHECK_TEXT in checks[LEAK_CHECK].observed
    assert checks[SILENT_CHECK].passed is True


def test_manual_steps_are_never_marked_as_passed() -> None:
    director, _ = _run_demo()

    manual = [check for check in director.checks() if check.passed is None]

    assert {check.step for check in manual} == {
        "IA caída",
        "Propuesta y decisión",
        "Publicación",
        "Cierre y acta",
    }


def test_muddy_water_is_sent_with_the_catalog_code_and_its_note() -> None:
    _, captured = _run_demo()

    muddy = [json.loads(body) for body in captured["readings"] if b'"MUDDY"' in body]

    assert len(muddy) == 1
    assert muddy[0]["note"].startswith("Agua con barro")


def test_leak_report_is_sent_only_at_the_hour_the_truth_says() -> None:
    scenario = load_scenario(PRESENTATION_YAML)
    run = run_simulation(scenario, DEMO_DAYS, scenario.meta.default_seed)

    assert scenario.demo is not None
    hours = _leak_report_hours(run, hour_of_day=scenario.demo.damage_report_hour_of_day)

    assert hours == frozenset({REPORT_HOUR})


def test_the_same_seed_sends_the_same_demo_requests() -> None:
    _, first = _run_demo()
    _, second = _run_demo()

    assert first == second


def test_demo_refuses_a_scenario_without_the_demo_section() -> None:
    result = CliRunner().invoke(cli.app, ["demo", "--scenario", str(NORMAL_YAML), "--sin-tablero"])

    assert result.exit_code == cli.EXIT_SCENARIO_ERROR
    assert "no tiene la sección demo" in result.output
