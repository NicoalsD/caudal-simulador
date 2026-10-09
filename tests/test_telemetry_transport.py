"""Signed telemetry transport: headers, canonical string, retries and error mapping."""

import base64
import json
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from caudal_sim.telemetry_transport import (
    MAX_POINTS_PER_BATCH,
    DeviceIdentity,
    SignedHttpTransport,
    TelemetryRequest,
    TransportRejectedError,
    TransportUnavailableError,
    canonical_string,
    telemetry_request,
)

BASE_URL = "http://api.test"
TELEMETRY_URL = f"{BASE_URL}/api/v1/devices/telemetry"
DEVICE_ID = UUID("0190f3a2-9999-7000-8000-000000000001")
EMPTY_BODY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ED25519_SIGNATURE_LENGTH = 86
NONCE_HEX_LENGTH = 32
FIXED_TIMESTAMP = 1791538200
SECOND_TIMESTAMP = FIXED_TIMESTAMP + 1
FIRST_NONCE = "3f9a1c4e7b2d408f9e6a5c1b2d3e4f50"
SECOND_NONCE = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
UNAUTHORIZED = 401
SERVER_ERROR = 503
POINT = {
    "id": "0190f3a2-6666-7000-8000-000000000001",
    "metric": "LEVEL",
    "value": 2.1,
    "observed_at": "2026-10-08T18:00:00-05:00",
}


def _identity() -> tuple[DeviceIdentity, Ed25519PrivateKey]:
    key = Ed25519PrivateKey.generate()
    return DeviceIdentity(DEVICE_ID, key), key


def _transport(
    handler: httpx.MockTransport | None,
    identity: DeviceIdentity,
    nonces: list[str],
    clock_values: list[int],
) -> SignedHttpTransport:
    http = httpx.Client(base_url=BASE_URL, transport=handler)
    return SignedHttpTransport(
        http,
        identity,
        clock=lambda: clock_values.pop(0),
        nonce_source=lambda: nonces.pop(0),
    )


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"accepted": 1, "duplicates": 0, "rejected": 0})


def test_request_carries_the_four_protocol_headers_and_a_valid_signature() -> None:
    identity, key = _identity()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok(request)

    transport = _transport(httpx.MockTransport(handler), identity, [FIRST_NONCE], [FIXED_TIMESTAMP])
    request = telemetry_request([POINT])

    transport.send(request)

    sent = seen[0]
    assert sent.headers["X-Device-Id"] == str(DEVICE_ID)
    assert sent.headers["X-Timestamp"] == str(FIXED_TIMESTAMP)
    assert sent.headers["X-Nonce"] == FIRST_NONCE
    signature_text = sent.headers["X-Signature"]
    assert len(signature_text) == ED25519_SIGNATURE_LENGTH
    padded = signature_text + "=" * (-len(signature_text) % 4)
    signature = base64.urlsafe_b64decode(padded)
    message = canonical_string(
        "POST", "/api/v1/devices/telemetry", FIXED_TIMESTAMP, FIRST_NONCE, sent.content
    )
    key.public_key().verify(signature, message)  # raises if the signature is wrong


def test_body_is_sent_byte_for_byte_as_it_was_built() -> None:
    identity, _ = _identity()
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        return _ok(request)

    request = telemetry_request([POINT])
    _transport(httpx.MockTransport(handler), identity, [FIRST_NONCE], [FIXED_TIMESTAMP]).send(
        request
    )

    assert seen == [request.body]
    assert json.loads(seen[0]) == {"points": [POINT]}


def test_canonical_string_has_five_lines_and_the_empty_body_hash() -> None:
    message = canonical_string("POST", "/api/v1/devices/telemetry", 1, FIRST_NONCE, b"")

    lines = message.decode("utf-8").split("\n")
    assert lines == [
        "POST",
        "/api/v1/devices/telemetry",
        "1",
        FIRST_NONCE,
        EMPTY_BODY_SHA256,
    ]


def test_each_attempt_gets_a_new_nonce_and_timestamp() -> None:
    identity, _ = _identity()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok(request)

    transport = _transport(
        httpx.MockTransport(handler),
        identity,
        [FIRST_NONCE, SECOND_NONCE],
        [FIXED_TIMESTAMP, SECOND_TIMESTAMP],
    )
    request = telemetry_request([POINT])
    transport.send(request)
    transport.send(request)

    nonces = [sent.headers["X-Nonce"] for sent in seen]
    assert nonces == [FIRST_NONCE, SECOND_NONCE]
    assert all(len(nonce) == NONCE_HEX_LENGTH for nonce in nonces)
    assert seen[0].content == seen[1].content


def test_connection_failure_and_server_errors_can_be_retried() -> None:
    identity, _ = _identity()

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=request)

    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(SERVER_ERROR, json={})

    request = telemetry_request([POINT])
    for handler in (refused, unavailable):
        transport = _transport(
            httpx.MockTransport(handler), identity, [FIRST_NONCE], [FIXED_TIMESTAMP]
        )
        with pytest.raises(TransportUnavailableError):
            transport.send(request)


def test_client_error_is_rejected_with_the_api_code_and_not_retried_as_unavailable() -> None:
    identity, _ = _identity()

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            UNAUTHORIZED, json={"error": {"code": "INVALID_SIGNATURE", "message": "x"}}
        )

    transport = _transport(
        httpx.MockTransport(unauthorized), identity, [FIRST_NONCE], [FIXED_TIMESTAMP]
    )

    with pytest.raises(TransportRejectedError) as error:
        transport.send(telemetry_request([POINT]))

    assert error.value.status_code == UNAUTHORIZED
    assert error.value.code == "INVALID_SIGNATURE"


def test_batch_builder_enforces_the_point_limit() -> None:
    with pytest.raises(ValueError, match="entre 1 y 100"):
        telemetry_request([])
    with pytest.raises(ValueError, match="entre 1 y 100"):
        telemetry_request([POINT] * (MAX_POINTS_PER_BATCH + 1))


def test_request_must_use_the_api_prefix() -> None:
    with pytest.raises(ValueError, match="/api/v1/"):
        TelemetryRequest("/telemetry", b"{}")
