"""Live mode against a mocked API: signed telemetry, readings, controls and auto-junta."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import SecretStr
from typer.testing import CliRunner

from caudal_sim import cli
from caudal_sim.api_client import CaudalApiClient
from caudal_sim.api_payload import ApiPayloadAdapter, ImportContext
from caudal_sim.builder import load_scenario
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.dashboard_session import ControlAction, ControlRequest, DashboardSession
from caudal_sim.live import (
    SENSOR_SILENT_HOURS,
    LiveAbortedError,
    LiveOptions,
    LiveRunner,
    LiveWiring,
    NetworkGate,
)
from caudal_sim.offline_buffer import OfflineBufferTransport
from caudal_sim.telemetry_transport import (
    DeviceIdentity,
    SignedHttpTransport,
    canonical_string,
)
from caudal_sim.terrain import SimulationRun, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
BASE = "https://api.test"
TELEMETRY_URL = f"{BASE}/api/v1/devices/telemetry"
READINGS_URL = f"{BASE}/api/v1/readings"
LOGIN_URL = f"{BASE}/api/v1/auth/login"
PROPOSALS_URL = f"{BASE}/api/v1/schedule-proposals"
SCHEDULE_URL = f"{BASE}/api/v1/public/guaitarilla-demo/schedule"
TOKEN = "token-de-prueba"
DEVICE_ID = UUID("0190f3a2-6666-7000-8000-000000000001")
AQUEDUCT_ID = UUID("0190f3a2-1111-7000-8000-000000000001")
TANK_ID = UUID("0190f3a2-2222-7000-8000-000000000001")
DAYS = 1
SEED = 42
HOUR_SECONDS = 1.0
EXPECTED_SPEED = 60
BASE64URL_PADDING = "="
SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
NONCE_HEADER = "X-Nonce"
DEVICE_HEADER = "X-Device-Id"
SHORT_RUN_HOURS = 3
SILENT_RUN_HOURS = SENSOR_SILENT_HOURS + 2


class _Harness:
    """Everything one live run needs, with the sleeper and the network under test control."""

    def __init__(self, sleep_hook: Callable[[float], None] | None = None) -> None:
        self.scenario = load_scenario(NORMAL_YAML)
        self.run: SimulationRun = run_simulation(self.scenario, DAYS, SEED)
        self.key = Ed25519PrivateKey.generate()
        self.session = DashboardSession(scenario=self.scenario.meta.name)
        self.sleeps: list[float] = []
        self._sleep_hook = sleep_hook
        self.api = CaudalApiClient(BASE, timeout_seconds=5.0)
        self.http = httpx.Client(base_url=BASE, timeout=5.0)
        self.gate = NetworkGate(SignedHttpTransport(self.http, DeviceIdentity(DEVICE_ID, self.key)))
        self.telemetry = OfflineBufferTransport.from_spec(
            self.gate, self.scenario.devices.buffer, sleeper=lambda _s: None
        )
        self.adapter = ApiPayloadAdapter(
            ImportContext(
                aqueduct_id=AQUEDUCT_ID,
                tank_id=TANK_ID,
                start=self.run.start,
                sector_slugs=tuple(sector.id for sector in self.scenario.sectors),
            )
        )
        self.board: CaudalApiClient | None = None

    def sleeper(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self._sleep_hook is not None:
            self._sleep_hook(seconds)

    def runner(self, options: LiveOptions) -> LiveRunner:
        wiring = LiveWiring(
            scenario=self.scenario,
            run=self.run,
            session=self.session,
            telemetry=self.telemetry,
            gate=self.gate,
            api=self.api,
            adapter=self.adapter,
            device_id=DEVICE_ID,
            sleeper=self.sleeper,
            board=self.board,
        )
        return LiveRunner(wiring, options)

    def close(self) -> None:
        self.api.close()
        self.http.close()
        if self.board is not None:
            self.board.close()


def _login_route(mock: respx.MockRouter) -> None:
    mock.post(LOGIN_URL).mock(return_value=httpx.Response(200, json={"access_token": TOKEN}))
    mock.post(READINGS_URL).mock(return_value=httpx.Response(201, json={}))


def _started(harness: _Harness) -> None:
    harness.api.login("operador.prueba", SecretStr("contraseña-de-prueba-larga"))


def _options(
    max_hours: int,
    *,
    hour_seconds: float = 0.0,
    auto_junta: bool = False,
) -> LiveOptions:
    return LiveOptions(hour_seconds=hour_seconds, max_hours=max_hours, auto_junta=auto_junta)


def _verify_signature(request: httpx.Request, public_key: Ed25519PublicKey) -> None:
    signature = request.headers[SIGNATURE_HEADER]
    padded = signature + BASE64URL_PADDING * (-len(signature) % 4)
    message = canonical_string(
        request.method,
        request.url.raw_path.decode("ascii"),
        int(request.headers[TIMESTAMP_HEADER]),
        request.headers[NONCE_HEADER],
        request.content,
    )
    public_key.verify(base64.urlsafe_b64decode(padded), message)


def test_telemetry_is_signed_with_the_device_key() -> None:
    harness = _Harness()
    try:
        with respx.mock(assert_all_called=False) as mock:
            _login_route(mock)
            telemetry = mock.post(TELEMETRY_URL).mock(
                return_value=httpx.Response(200, json={"accepted": 1, "duplicates": 0})
            )
            _started(harness)

            harness.runner(_options(SHORT_RUN_HOURS)).run()

            assert telemetry.call_count == SHORT_RUN_HOURS
            request = telemetry.calls.last.request
            assert request.headers[DEVICE_HEADER] == str(DEVICE_ID)
            _verify_signature(request, harness.key.public_key())
    finally:
        harness.close()


def test_readings_are_sent_with_the_operator_token() -> None:
    harness = _Harness()
    expected = sum(
        1 for reading in harness.run.observed.readings if reading.sent_hour_index < SHORT_RUN_HOURS
    )
    try:
        with respx.mock(assert_all_called=False) as mock:
            _login_route(mock)
            mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
            readings = mock.post(READINGS_URL).mock(return_value=httpx.Response(201, json={}))
            _started(harness)

            report = harness.runner(_options(HOURS_PER_DAY)).run()

            assert report.readings_sent == readings.call_count
            assert readings.call_count >= expected
            assert readings.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    finally:
        harness.close()


def test_the_same_seed_sends_the_same_telemetry_bytes() -> None:
    bodies: list[list[bytes]] = []
    for _ in range(2):
        harness = _Harness()
        try:
            with respx.mock(assert_all_called=False) as mock:
                _login_route(mock)
                telemetry = mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
                _started(harness)
                harness.runner(_options(SHORT_RUN_HOURS)).run()
                bodies.append([call.request.content for call in telemetry.calls])
        finally:
            harness.close()

    assert bodies[0] == bodies[1]


def test_telemetry_kept_while_the_network_is_down_is_sent_in_order() -> None:
    restored: list[bool] = []

    def bring_network_back(_seconds: float) -> None:
        if not restored:
            restored.append(True)
            harness.session.request_control(ControlRequest(ControlAction.NETWORK_UP))

    harness = _Harness(sleep_hook=bring_network_back)
    harness.session.request_control(ControlRequest(ControlAction.NETWORK_DOWN))
    try:
        with respx.mock(assert_all_called=False) as mock:
            _login_route(mock)
            telemetry = mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
            _started(harness)

            harness.runner(_options(SHORT_RUN_HOURS, hour_seconds=HOUR_SECONDS)).run()

            observed = [_observed_at(call.request.content) for call in telemetry.calls]
            assert telemetry.call_count == SHORT_RUN_HOURS
            assert observed == sorted(observed)
            assert harness.telemetry.pending == 0
    finally:
        harness.close()


def test_silent_sensor_sends_its_held_points_later_with_their_old_time() -> None:
    harness = _Harness()
    harness.session.request_control(ControlRequest(ControlAction.SENSOR_SILENT))
    try:
        with respx.mock(assert_all_called=False) as mock:
            _login_route(mock)
            telemetry = mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
            _started(harness)

            harness.runner(_options(SILENT_RUN_HOURS)).run()

            first_sent = _observed_at(telemetry.calls[0].request.content)
            assert first_sent == harness.run.start.isoformat()
            assert telemetry.call_count == SILENT_RUN_HOURS
    finally:
        harness.close()


def test_pause_waits_until_the_dashboard_resumes_the_clock() -> None:
    def resume(_seconds: float) -> None:
        harness.session.request_control(ControlRequest(ControlAction.RESUME))

    harness = _Harness(sleep_hook=resume)
    harness.session.request_control(ControlRequest(ControlAction.PAUSE))
    try:
        with respx.mock(assert_all_called=False) as mock:
            _login_route(mock)
            mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
            _started(harness)

            report = harness.runner(_options(SHORT_RUN_HOURS)).run()

            assert report.hours == SHORT_RUN_HOURS
            assert harness.session.paused is False
            assert harness.sleeps
    finally:
        harness.close()


def test_speed_shortens_the_time_between_hours() -> None:
    harness = _Harness()
    harness.session.request_control(ControlRequest(ControlAction.SET_SPEED, factor=EXPECTED_SPEED))
    try:
        with respx.mock(assert_all_called=False) as mock:
            _login_route(mock)
            mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
            _started(harness)

            harness.runner(_options(SHORT_RUN_HOURS, hour_seconds=HOUR_SECONDS)).run()

            assert harness.sleeps == pytest.approx([HOUR_SECONDS / EXPECTED_SPEED] * 2)
    finally:
        harness.close()


def test_leak_and_heavy_rain_are_reported_as_not_applied_yet() -> None:
    harness = _Harness()
    harness.session.request_control(ControlRequest(ControlAction.LEAK))
    try:
        with respx.mock(assert_all_called=False) as mock:
            _login_route(mock)
            mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
            _started(harness)

            report = harness.runner(_options(1)).run()

            assert report.unsupported_controls == [str(ControlAction.LEAK)]
    finally:
        harness.close()


def test_auto_junta_approves_the_pending_proposals() -> None:
    harness = _Harness()
    try:
        with respx.mock(assert_all_called=False) as mock:
            _login_route(mock)
            mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
            mock.get(f"{PROPOSALS_URL}?status=PENDING_REVIEW").mock(
                return_value=httpx.Response(
                    200, json={"items": [{"id": "propuesta-1", "lock_version": 0}]}
                )
            )
            approve = mock.post(f"{PROPOSALS_URL}/propuesta-1/approve").mock(
                return_value=httpx.Response(200, json={"status": "APPROVED"})
            )
            _login_route(mock)
            _started(harness)
            harness.board = CaudalApiClient(BASE, timeout_seconds=5.0)
            harness.board.login("junta.prueba", SecretStr("contraseña-de-prueba-larga"))

            report = harness.runner(_options(1, auto_junta=True)).run()

            assert approve.call_count == 1
            assert report.approvals == 1
            assert approve.calls.last.request.read() == b'{"lock_version":0}'
    finally:
        harness.close()


def test_a_full_buffer_stops_the_run_with_a_spanish_message() -> None:
    harness = _Harness()
    harness.telemetry = OfflineBufferTransport(
        harness.gate, capacity=1, max_attempts=1, sleeper=lambda _s: None
    )
    harness.session.request_control(ControlRequest(ControlAction.NETWORK_DOWN))
    try:
        with respx.mock(assert_all_called=False) as mock:
            _login_route(mock)
            mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
            _started(harness)

            with pytest.raises(LiveAbortedError, match="buffer sin conexión está lleno"):
                harness.runner(_options(SHORT_RUN_HOURS)).run()
    finally:
        harness.close()


def test_live_refuses_to_send_when_the_target_is_not_the_demo_aqueduct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_path = tmp_path / "keys" / "ed25519-private.pem"
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    env = {
        "CAUDAL_SIM_API_BASE_URL": BASE,
        "CAUDAL_SIM_API_USERNAME": "project.team",
        "CAUDAL_SIM_API_PASSWORD": "contraseña-de-prueba-larga",
        "CAUDAL_SIM_DEMO_AQUEDUCT_SLUG": "guaitarilla-demo",
        "CAUDAL_SIM_AQUEDUCT_ID": str(AQUEDUCT_ID),
        "CAUDAL_SIM_TANK_ID": str(TANK_ID),
        "CAUDAL_SIM_PRIVATE_KEY_PATH": str(key_path),
        "CAUDAL_SIM_LIVE_OPERATOR_USERNAME": "operador.prueba",
        "CAUDAL_SIM_LIVE_OPERATOR_PASSWORD": "contraseña-de-prueba-larga",
        "CAUDAL_SIM_LIVE_DEVICE_ID": str(DEVICE_ID),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_run_live", lambda *_args: pytest.fail("no debe iniciar"))

    with respx.mock(assert_all_called=False) as mock:
        mock.get(SCHEDULE_URL).mock(
            return_value=httpx.Response(200, json={"aqueduct": {"is_demo": False}})
        )
        telemetry = mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(200, json={}))
        result = CliRunner().invoke(
            cli.app,
            ["live", "--scenario", str(NORMAL_YAML), "--max-hours", "2", "--sin-tablero"],
        )

    assert result.exit_code == cli.EXIT_LIVE_ERROR
    assert "no es el acueducto de demostración" in result.output
    assert telemetry.call_count == 0


def _observed_at(body: bytes) -> str:
    points = json.loads(body)["points"]
    return str(points[0]["observed_at"])
