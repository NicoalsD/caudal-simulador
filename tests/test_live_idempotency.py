"""Idempotency and event order of the live mode: retries keep identifiers and bodies."""

from __future__ import annotations

import json
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import httpx
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

from caudal_sim.api_client import CaudalApiClient
from caudal_sim.api_payload import ApiPayloadAdapter, ImportContext
from caudal_sim.builder import load_scenario
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.dashboard_session import DashboardSession
from caudal_sim.event_bus import SimulationEvent, SimulationEventKind
from caudal_sim.live import LiveOptions, LiveRunner, LiveWiring, NetworkGate
from caudal_sim.offline_buffer import OfflineBufferTransport
from caudal_sim.telemetry_transport import DeviceIdentity, SignedHttpTransport
from caudal_sim.terrain import run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
BASE = "https://api.test"
TELEMETRY_URL = f"{BASE}/api/v1/devices/telemetry"
READINGS_URL = f"{BASE}/api/v1/readings"
LOGIN_URL = f"{BASE}/api/v1/auth/login"
DEVICE_ID = UUID("0190f3a2-6666-7000-8000-000000000001")
AQUEDUCT_ID = UUID("0190f3a2-1111-7000-8000-000000000001")
TANK_ID = UUID("0190f3a2-2222-7000-8000-000000000001")
SEED = 42
DAYS = 1
SERVICE_UNAVAILABLE = 503
HTTP_CREATED = 201
HTTP_OK = 200
OUTAGE_HOURS = 3
MIN_ATTEMPTS = 2


class _Rig:
    """One live wiring with its own HTTP client, so each test starts from a clean state."""

    def __init__(self, sleeper: Callable[[float], None] | None = None) -> None:
        scenario = load_scenario(NORMAL_YAML)
        self.run = run_simulation(scenario, DAYS, SEED)
        self.session = DashboardSession(scenario=scenario.meta.name)
        self.http = httpx.Client(base_url=BASE, timeout=5.0)
        self.gate = NetworkGate(
            SignedHttpTransport(self.http, DeviceIdentity(DEVICE_ID, Ed25519PrivateKey.generate()))
        )
        self.api = CaudalApiClient(BASE, timeout_seconds=5.0)
        self.wiring = LiveWiring(
            scenario=scenario,
            run=self.run,
            session=self.session,
            telemetry=OfflineBufferTransport.from_spec(
                self.gate, scenario.devices.buffer, sleeper=lambda _s: None
            ),
            gate=self.gate,
            api=self.api,
            adapter=ApiPayloadAdapter(
                ImportContext(
                    aqueduct_id=AQUEDUCT_ID,
                    tank_id=TANK_ID,
                    start=self.run.start,
                    sector_slugs=tuple(sector.id for sector in scenario.sectors),
                )
            ),
            device_id=DEVICE_ID,
            tank_id=TANK_ID,
            sleeper=sleeper or (lambda _s: None),
        )

    def play(self, hours: int, hour_seconds: float = 0.0) -> None:
        self.api.login("operador.prueba", SecretStr("contraseña-de-prueba-larga"))
        LiveRunner(self.wiring, LiveOptions(hour_seconds=hour_seconds, max_hours=hours)).run()

    def close(self) -> None:
        self.api.close()
        self.http.close()


def _mock_api(mock: respx.MockRouter) -> None:
    mock.post(LOGIN_URL).mock(return_value=httpx.Response(HTTP_OK, json={"access_token": "t"}))
    mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(HTTP_OK, json={}))


def test_the_same_seed_sends_the_same_reading_identifiers_and_bodies() -> None:
    runs: list[list[bytes]] = []
    for _ in range(2):
        rig = _Rig()
        try:
            with respx.mock(assert_all_called=False) as mock:
                _mock_api(mock)
                readings = mock.post(READINGS_URL).mock(
                    return_value=httpx.Response(HTTP_CREATED, json={})
                )
                rig.play(HOURS_PER_DAY)
                runs.append([call.request.content for call in readings.calls])
        finally:
            rig.close()

    assert runs[0]
    assert runs[0] == runs[1]


def test_a_reading_retried_after_a_server_error_keeps_its_body() -> None:
    attempts: list[bytes] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts.append(request.content)
        if len(attempts) == 1:
            return httpx.Response(SERVICE_UNAVAILABLE, json={})
        return httpx.Response(HTTP_CREATED, json={})

    rig = _Rig()
    try:
        with respx.mock(assert_all_called=False) as mock:
            _mock_api(mock)
            mock.post(READINGS_URL).mock(side_effect=flaky)
            rig.play(HOURS_PER_DAY)
    finally:
        rig.close()

    assert len(attempts) >= MIN_ATTEMPTS
    assert attempts[0] == attempts[1]


def test_a_replayed_reading_is_counted_as_sent_not_rejected() -> None:
    rig = _Rig()
    try:
        with respx.mock(assert_all_called=False) as mock:
            _mock_api(mock)
            mock.post(READINGS_URL).mock(
                return_value=httpx.Response(
                    HTTP_OK, json={"idempotent_replay": True, "reading": {}}
                )
            )
            rig.play(HOURS_PER_DAY)
            report = LiveRunner(rig.wiring, LiveOptions(hour_seconds=0.0, max_hours=1)).run()
    finally:
        rig.close()

    assert report.readings_rejected == 0


def test_telemetry_sent_after_an_outage_matches_an_uninterrupted_run() -> None:
    def bodies(outage: bool) -> list[bytes]:
        restored: list[bool] = []

        def bring_network_back(_seconds: float) -> None:
            if outage and not restored:
                restored.append(True)
                rig.gate.set_online(True)

        rig = _Rig(sleeper=bring_network_back)
        if outage:
            rig.gate.set_online(False)
        try:
            with respx.mock(assert_all_called=False) as mock:
                mock.post(LOGIN_URL).mock(
                    return_value=httpx.Response(HTTP_OK, json={"access_token": "t"})
                )
                telemetry = mock.post(TELEMETRY_URL).mock(
                    return_value=httpx.Response(HTTP_OK, json={})
                )
                rig.play(OUTAGE_HOURS, hour_seconds=1.0)
                return [call.request.content for call in telemetry.calls]
        finally:
            rig.close()

    assert bodies(outage=True) == bodies(outage=False)


def test_valve_events_arrive_in_time_order_and_alternate_per_sector() -> None:
    rig = _Rig()
    events: list[SimulationEvent] = []

    class Recorder:
        def on_event(self, event: SimulationEvent) -> None:
            events.append(event)

    rig.session.bus.subscribe(Recorder())
    try:
        with respx.mock(assert_all_called=False) as mock:
            _mock_api(mock)
            mock.post(READINGS_URL).mock(return_value=httpx.Response(HTTP_CREATED, json={}))
            rig.play(HOURS_PER_DAY)
    finally:
        rig.close()

    valve_events = [e for e in events if e.kind is SimulationEventKind.VALVE_STATE_CHANGED]
    assert valve_events
    times = [event.occurred_at for event in valve_events]
    assert times == sorted(times)
    for sector in {event.subject_id for event in valve_events}:
        details = [event.detail for event in valve_events if event.subject_id == sector]
        assert all(left != right for left, right in pairwise(details))


def test_telemetry_body_is_one_canonical_json_object_with_uuid_ids() -> None:
    rig = _Rig()
    try:
        with respx.mock(assert_all_called=False) as mock:
            _mock_api(mock)
            telemetry = mock.post(TELEMETRY_URL).mock(return_value=httpx.Response(HTTP_OK, json={}))
            rig.play(1)
            body = telemetry.calls[0].request.content
    finally:
        rig.close()

    parsed = json.loads(body)
    assert list(parsed) == ["points"]
    assert UUID(parsed["points"][0]["id"])
