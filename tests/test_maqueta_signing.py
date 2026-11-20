"""Signature of the maqueta requests, checked by an independent verifier (the fake API).

The verifier rebuilds the canonical string of section 2.2 of the device protocol: method, path,
time, nonce and the SHA-256 of the body bytes, joined by LF. A request whose signed bytes change
is refused, and so is a reused nonce.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from caudal_sim.api_client import encode_json
from caudal_sim.command_channel import AckResult
from caudal_sim.maqueta_commands import HttpCommandSource
from caudal_sim.telemetry_transport import (
    DeviceIdentity,
    SignedHttpTransport,
    TransportRejectedError,
    telemetry_request,
)
from maqueta_fake_api import (
    SENSOR_DEVICE,
    TELEMETRY_PATH,
    VALVE_1,
    VALVE_1_DEVICE,
    FakeApi,
    make_setup,
)

BASE_URL = "http://api.test"
EMPTY_BODY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
NONCE_PATTERN = re.compile(r"[0-9a-f]{32}")
COMMANDS_PATH = "/api/v1/devices/commands"
COMMAND_ID = UUID("0190f3a2-7777-7000-8000-000000000009")
UNAUTHORIZED = 401


def _point() -> dict[str, object]:
    return {
        "id": "0190f3a2-6666-7000-8000-000000000001",
        "metric": "LEVEL",
        "value": 0.12,
        "observed_at": NOW.isoformat(),
    }


def _http(api: FakeApi) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, transport=api.transport())


def test_a_get_is_signed_over_the_hash_of_the_empty_body() -> None:
    setup = make_setup()
    source = HttpCommandSource(
        SignedHttpTransport(_http(setup.api), setup.identities.outlets[0][0]),
        VALVE_1,
        datetime.fromisoformat,
    )

    source.deliver(VALVE_1, NOW)

    request = setup.api.requests[0]
    assert request.method == "GET"
    assert request.path == COMMANDS_PATH
    assert request.verified is True
    assert request.body == b""
    assert request.headers["x-device-id"] == str(VALVE_1_DEVICE)
    assert NONCE_PATTERN.fullmatch(request.headers["x-nonce"])
    assert request.headers["x-timestamp"].isdigit()
    assert hashlib.sha256(b"").hexdigest() == EMPTY_BODY_SHA256


def test_each_request_gets_a_new_nonce() -> None:
    setup = make_setup()
    transport = SignedHttpTransport(_http(setup.api), setup.identities.sensor)

    transport.send(telemetry_request([_point()]))
    transport.send(telemetry_request([_point()]))

    first, second = (request.headers["x-nonce"] for request in setup.api.requests)
    assert first != second


def test_the_ack_body_is_the_signed_body_byte_for_byte() -> None:
    setup = make_setup()
    source = HttpCommandSource(
        SignedHttpTransport(_http(setup.api), setup.identities.outlets[0][0]),
        VALVE_1,
        datetime.fromisoformat,
    )

    source.acknowledge(COMMAND_ID, AckResult.ACKED, "Válvula en la posición pedida.", NOW)

    request = setup.api.requests[-1]
    expected = {"result": "ACKED", "detail": "Válvula en la posición pedida."}
    assert request.verified is True
    assert request.body == encode_json(expected)
    assert json.loads(request.body) == expected
    assert setup.api.acks[-1]["command_id"] == str(COMMAND_ID)


def test_a_changed_signed_time_is_refused_by_the_api() -> None:
    setup = make_setup()
    http = httpx.Client(base_url=BASE_URL, transport=_tampered(setup.api, timestamp=True))

    with pytest.raises(TransportRejectedError) as error:
        SignedHttpTransport(http, setup.identities.sensor).send(telemetry_request([_point()]))

    assert error.value.status_code == UNAUTHORIZED
    assert error.value.code == "INVALID_SIGNATURE"


def test_a_changed_body_is_refused_by_the_api() -> None:
    setup = make_setup()
    http = httpx.Client(base_url=BASE_URL, transport=_tampered(setup.api, body=True))

    with pytest.raises(TransportRejectedError) as error:
        SignedHttpTransport(http, setup.identities.sensor).send(telemetry_request([_point()]))

    assert error.value.code == "INVALID_SIGNATURE"


def test_a_reused_nonce_is_refused_as_a_replay() -> None:
    setup = make_setup()
    transport = SignedHttpTransport(
        _http(setup.api), setup.identities.sensor, nonce_source=lambda: "0" * 32
    )
    transport.send(telemetry_request([_point()]))

    with pytest.raises(TransportRejectedError) as error:
        transport.send(telemetry_request([_point()]))

    assert error.value.code == "NONCE_REPLAY"


def test_the_sensor_telemetry_is_signed_with_the_sensor_key() -> None:
    setup = make_setup()

    SignedHttpTransport(_http(setup.api), setup.identities.sensor).send(
        telemetry_request([_point()])
    )

    request = setup.api.requests[0]
    assert request.path == TELEMETRY_PATH
    assert request.device_id == str(SENSOR_DEVICE)
    assert request.verified is True


def test_a_key_of_one_device_does_not_verify_another_device() -> None:
    setup = make_setup()
    impostor = DeviceIdentity(VALVE_1_DEVICE, setup.identities.sensor.private_key)

    with pytest.raises(TransportRejectedError) as error:
        SignedHttpTransport(_http(setup.api), impostor).send(telemetry_request([_point()]))

    assert error.value.code == "INVALID_SIGNATURE"


def _tampered(api: FakeApi, *, timestamp: bool = False, body: bool = False) -> httpx.MockTransport:
    """Changes one signed element after the signature is made, as a man in the middle would."""

    def handler(request: httpx.Request) -> httpx.Response:
        if timestamp:
            request.headers["x-timestamp"] = str(int(request.headers["x-timestamp"]) + 1)
        if body:
            headers = [(k, v) for k, v in request.headers.items() if k.lower() != "content-length"]
            request = httpx.Request(
                request.method, request.url, headers=headers, content=request.content + b" "
            )
        return api.handle(request)

    return httpx.MockTransport(handler)
