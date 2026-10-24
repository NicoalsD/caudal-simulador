"""Manual scenario controls of the dashboard: queued conditions, never valve moves."""

from fastapi.testclient import TestClient

from caudal_sim.dashboard_api import CONTROLS_PATH, STATE_PATH, create_dashboard_app
from caudal_sim.dashboard_session import ControlAction, ControlRequest, DashboardSession

HTTP_ACCEPTED = 202
HTTP_UNPROCESSABLE = 422
FAST_SPEED = 60


def _client(session: DashboardSession) -> TestClient:
    return TestClient(create_dashboard_app(session))


def test_leak_control_is_queued_for_the_simulation() -> None:
    session = DashboardSession(scenario="normal-year")

    response = _client(session).post(CONTROLS_PATH, json={"action": "LEAK"})

    assert response.status_code == HTTP_ACCEPTED
    assert response.json() == {"action": "LEAK", "factor": None, "status": "QUEUED"}
    assert session.drain_controls() == (ControlRequest(ControlAction.LEAK),)
    assert session.drain_controls() == ()


def test_pause_and_speed_show_in_the_state() -> None:
    session = DashboardSession(scenario="normal-year")
    client = _client(session)

    client.post(CONTROLS_PATH, json={"action": "PAUSE"})
    client.post(CONTROLS_PATH, json={"action": "SET_SPEED", "factor": FAST_SPEED})
    state = client.get(STATE_PATH).json()

    assert state["paused"] is True
    assert state["speed_factor"] == FAST_SPEED
    client.post(CONTROLS_PATH, json={"action": "RESUME"})
    assert client.get(STATE_PATH).json()["paused"] is False


def test_valves_cannot_be_opened_or_closed_from_the_dashboard() -> None:
    client = _client(DashboardSession(scenario="normal-year"))

    for action in ("OPEN_VALVE", "CLOSE_VALVE", "OPEN", "CLOSE"):
        response = client.post(CONTROLS_PATH, json={"action": action})
        assert response.status_code == HTTP_UNPROCESSABLE


def test_speed_needs_one_of_the_offered_factors() -> None:
    client = _client(DashboardSession(scenario="normal-year"))

    missing = client.post(CONTROLS_PATH, json={"action": "SET_SPEED"})
    unknown = client.post(CONTROLS_PATH, json={"action": "SET_SPEED", "factor": 7})
    unexpected = client.post(CONTROLS_PATH, json={"action": "LEAK", "factor": 10})

    assert missing.status_code == HTTP_UNPROCESSABLE
    assert unknown.status_code == HTTP_UNPROCESSABLE
    assert unexpected.status_code == HTTP_UNPROCESSABLE


def test_unknown_fields_are_rejected() -> None:
    response = _client(DashboardSession(scenario="normal-year")).post(
        CONTROLS_PATH, json={"action": "LEAK", "valve_id": "x"}
    )

    assert response.status_code == HTTP_UNPROCESSABLE
