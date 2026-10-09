"""API client tests with respx: no real network calls."""

import json
from uuid import UUID

import httpx
import pytest
import respx
from pydantic import SecretStr

from caudal_sim.api_client import ApiError, CaudalApiClient
from caudal_sim.config import SimulatorSettings

BASE_URL = "http://api.test"
LOGIN_URL = f"{BASE_URL}/api/v1/auth/login"
IMPORT_PATH = "/api/v1/imports/readings"
USERNAME = "project.team"
PASSWORD = SecretStr("contraseña-de-prueba-larga")
TOKEN = "token-de-prueba"
TIMEOUT_SECONDS = 5.0
FORBIDDEN = 403
BAD_GATEWAY = 502
UNAUTHORIZED = 401


def _client() -> CaudalApiClient:
    return CaudalApiClient(BASE_URL, timeout_seconds=TIMEOUT_SECONDS)


def test_login_sends_credentials_and_import_sends_bearer_token() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        login = router.post("/api/v1/auth/login").respond(
            200, json={"access_token": TOKEN, "token_type": "Bearer"}
        )
        imported = router.post(IMPORT_PATH).respond(201, json={"rows_accepted": 1})

        with _client() as client:
            client.login(USERNAME, PASSWORD)
            result = client.post_import(IMPORT_PATH, {"rows": []})

    sent_login = json.loads(login.calls.last.request.content)
    assert sent_login == {"username": USERNAME, "password": PASSWORD.get_secret_value()}
    assert imported.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert result == {"rows_accepted": 1}


def test_import_without_login_is_refused_before_any_request() -> None:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        route = router.post(IMPORT_PATH).respond(201)

        with _client() as client, pytest.raises(ApiError) as caught:
            client.post_import(IMPORT_PATH, {"rows": []})

    assert caught.value.code == "UNAUTHORIZED"
    assert not route.called


def test_canonical_error_is_mapped_to_code_and_message() -> None:
    body = {
        "error": {
            "code": "DEMO_ONLY",
            "message": "Esta operación solo aplica al acueducto de demostración.",
            "details": {},
            "request_id": "7f3c2a9e-1d4b-4e1a-9c0e-2b8f5a6d1e33",
        }
    }
    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/auth/login").respond(200, json={"access_token": TOKEN})
        router.post(IMPORT_PATH).respond(FORBIDDEN, json=body)

        with _client() as client:
            client.login(USERNAME, PASSWORD)
            with pytest.raises(ApiError) as caught:
                client.post_import(IMPORT_PATH, {"rows": []})

    assert caught.value.status_code == FORBIDDEN
    assert caught.value.code == "DEMO_ONLY"
    assert caught.value.message == body["error"]["message"]


def test_non_canonical_error_body_becomes_unexpected_response() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/auth/login").respond(BAD_GATEWAY, text="<html>bad gateway</html>")

        with _client() as client, pytest.raises(ApiError) as caught:
            client.login(USERNAME, PASSWORD)

    assert caught.value.status_code == BAD_GATEWAY
    assert caught.value.code == "UNEXPECTED_RESPONSE"


def test_password_never_appears_in_errors_or_their_repr() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/auth/login").respond(
            UNAUTHORIZED,
            json={
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "Usuario o contraseña incorrectos.",
                }
            },
        )

        with _client() as client, pytest.raises(ApiError) as caught:
            client.login(USERNAME, PASSWORD)

    assert PASSWORD.get_secret_value() not in repr(caught.value)
    assert PASSWORD.get_secret_value() not in str(caught.value)
    assert caught.value.code == "INVALID_CREDENTIALS"


def test_network_failure_becomes_a_spanish_api_error() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/auth/login").mock(side_effect=httpx.ConnectError("sin red"))

        with _client() as client, pytest.raises(ApiError) as caught:
            client.login(USERNAME, PASSWORD)

    assert caught.value.code == "CONNECTION_FAILED"
    assert "No se pudo conectar" in caught.value.message


def test_settings_read_the_environment_and_hide_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAUDAL_SIM_API_BASE_URL", BASE_URL)
    monkeypatch.setenv("CAUDAL_SIM_API_USERNAME", USERNAME)
    monkeypatch.setenv("CAUDAL_SIM_API_PASSWORD", PASSWORD.get_secret_value())
    monkeypatch.setenv("CAUDAL_SIM_DEMO_AQUEDUCT_SLUG", "demo")
    monkeypatch.setenv("CAUDAL_SIM_AQUEDUCT_ID", "0190f3a2-0000-7000-8000-0000000000bb")
    monkeypatch.setenv("CAUDAL_SIM_TANK_ID", "0190f3a2-2222-7000-8000-000000000001")

    settings = SimulatorSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.api_username == USERNAME
    assert settings.aqueduct_id == UUID("0190f3a2-0000-7000-8000-0000000000bb")
    assert PASSWORD.get_secret_value() not in repr(settings)
