"""Fake caudal-backend for the maqueta tests: no network, real signature checks.

The fake verifies each request with the public key of its device, rebuilding the canonical
string on its own (`Protocolo-de-dispositivos.md`, section 2.2), so the tests prove the signing
of the simulator and do not trust it. A bad signature or a reused nonce gets the 401 of the API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from caudal_sim.maqueta_device import MaquetaIdentities
from caudal_sim.telemetry_transport import DeviceIdentity

ACK_PATH = re.compile(r"/api/v1/devices/commands/(?P<id>[0-9a-f-]{36})/ack")
COMMANDS_PATH = "/api/v1/devices/commands"
TELEMETRY_PATH = "/api/v1/devices/telemetry"
DEVICE_HEADER = "X-Device-Id"
TIMESTAMP_HEADER = "X-Timestamp"
NONCE_HEADER = "X-Nonce"
SIGNATURE_HEADER = "X-Signature"
OK = 200
UNAUTHORIZED = 401
RATE_LIMITED_CODE = "RATE_LIMITED"
RATE_LIMITED = 429
CONFLICT = 409
NOT_FOUND = 404


@dataclass
class RecordedRequest:
    """One request the fake received, with the result of its signature check."""

    method: str
    path: str
    device_id: str
    headers: dict[str, str]
    body: bytes
    verified: bool


@dataclass
class FakeApi:
    """Keyed by device identifier. Commands are served until their ack is accepted."""

    public_keys: dict[str, Ed25519PublicKey]
    commands: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    get_statuses: list[int] = field(default_factory=list)
    telemetry_statuses: list[int] = field(default_factory=list)
    ack_status: int = OK
    requests: list[RecordedRequest] = field(default_factory=list)
    acks: list[dict[str, Any]] = field(default_factory=list)
    telemetry: list[dict[str, Any]] = field(default_factory=list)
    _nonces: set[str] = field(default_factory=set)
    _acked: set[str] = field(default_factory=set)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        device = request.headers.get(DEVICE_HEADER, "")
        path = request.url.path
        reason = self._check_signature(request, device)
        verified = reason is None
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path=path,
                device_id=device,
                headers=dict(request.headers),
                body=request.content,
                verified=verified,
            )
        )
        if reason is not None:
            return _error(UNAUTHORIZED, reason)
        if request.method == "GET" and path == COMMANDS_PATH:
            return self._serve_commands(device)
        match = ACK_PATH.fullmatch(path)
        if request.method == "POST" and match:
            return self._accept_ack(device, match.group("id"), request.content)
        if request.method == "POST" and path == TELEMETRY_PATH:
            return self._accept_telemetry(request.content)
        return _error(NOT_FOUND, "NOT_FOUND")

    def _serve_commands(self, device: str) -> httpx.Response:
        status = self.get_statuses.pop(0) if self.get_statuses else OK
        if status != OK:
            return _error(status, _code_for(status))
        items = [item for item in self.commands.get(device, []) if item["id"] not in self._acked]
        return httpx.Response(OK, json={"items": items})

    def _accept_ack(self, device: str, command_id: str, body: bytes) -> httpx.Response:
        self.acks.append(
            {"device": device, "command_id": command_id, "body": body, "payload": json.loads(body)}
        )
        if self.ack_status != OK:
            return _error(self.ack_status, "INVALID_STATE_TRANSITION")
        self._acked.add(command_id)
        return httpx.Response(OK, json={"id": command_id})

    def _accept_telemetry(self, body: bytes) -> httpx.Response:
        status = self.telemetry_statuses.pop(0) if self.telemetry_statuses else OK
        if status != OK:
            return _error(status, _code_for(status))
        payload = json.loads(body)
        self.telemetry.append(payload)
        return httpx.Response(
            OK,
            json={
                "accepted": len(payload["points"]),
                "duplicates": 0,
                "rejected": 0,
                "results": [],
            },
        )

    def _check_signature(self, request: httpx.Request, device: str) -> str | None:
        """None when the request is valid; otherwise the error code the API would answer."""
        key = self.public_keys.get(device)
        timestamp = request.headers.get(TIMESTAMP_HEADER, "")
        nonce = request.headers.get(NONCE_HEADER, "")
        signature = request.headers.get(SIGNATURE_HEADER, "")
        if key is None or not timestamp or not nonce or not signature:
            return "INVALID_SIGNATURE"
        body_sha = hashlib.sha256(request.content).hexdigest()
        canonical = "\n".join(
            [request.method, request.url.path, timestamp, nonce, body_sha]
        ).encode("utf-8")
        try:
            key.verify(_b64url_decode(signature), canonical)
        except (InvalidSignature, ValueError):
            return "INVALID_SIGNATURE"
        if nonce in self._nonces:
            return "NONCE_REPLAY"
        self._nonces.add(nonce)
        return None


def command_item(
    command_id: str,
    valve_id: UUID,
    command: str,
    not_before: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    """One item of `GET /devices/commands`, with the snake_case fields of the API."""
    return {
        "id": command_id,
        "valve_id": str(valve_id),
        "command": command,
        "not_before": not_before.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def _code_for(status: int) -> str:
    return RATE_LIMITED_CODE if status == RATE_LIMITED else "VALIDATION_ERROR"


def _error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": code}})


def _b64url_decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded)


SENSOR_DEVICE = UUID("0190f3a2-0000-7000-8000-0000000000a1")
VALVE_1_DEVICE = UUID("0190f3a2-0000-7000-8000-0000000000a2")
VALVE_2_DEVICE = UUID("0190f3a2-0000-7000-8000-0000000000a3")
VALVE_1 = UUID("0190f3a2-0000-7000-8000-0000000000b1")
VALVE_2 = UUID("0190f3a2-0000-7000-8000-0000000000b2")


@dataclass(frozen=True)
class MaquetaSetup:
    """Identities of the maqueta with the public keys the fake API knows. Keys are throwaway."""

    identities: Any
    api: FakeApi


def make_setup() -> MaquetaSetup:
    """Three generated keys, one per signed identity, and a fake API that trusts them."""
    keys = {
        device: Ed25519PrivateKey.generate()
        for device in (SENSOR_DEVICE, VALVE_1_DEVICE, VALVE_2_DEVICE)
    }
    identities = MaquetaIdentities(
        sensor=DeviceIdentity(SENSOR_DEVICE, keys[SENSOR_DEVICE]),
        outlets=(
            (DeviceIdentity(VALVE_1_DEVICE, keys[VALVE_1_DEVICE]), VALVE_1),
            (DeviceIdentity(VALVE_2_DEVICE, keys[VALVE_2_DEVICE]), VALVE_2),
        ),
    )
    public = {str(device): key.public_key() for device, key in keys.items()}
    return MaquetaSetup(identities=identities, api=FakeApi(public_keys=public))
