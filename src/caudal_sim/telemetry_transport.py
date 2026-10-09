"""Telemetry transport of a simulated device: signed HTTP requests to the CAUDAL API.

Every request of a device carries four headers (`Protocolo-de-dispositivos.md`, section 2):
the device identifier, the timestamp in whole seconds, a 128-bit nonce in hexadecimal, and an
Ed25519 signature of the canonical string. The canonical string has five lines joined by LF:
method, path, timestamp, nonce and the SHA-256 of the body bytes, as they travel on the wire.

The payload of a request is fixed when it is built. The signature is made again for every
attempt, with a new timestamp and nonce, so a retry never repeats a nonce.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from caudal_sim.api_client import JSON_CONTENT_TYPE, encode_json
from caudal_sim.signing import sign_bytes

TELEMETRY_PATH = "/api/v1/devices/telemetry"
API_PATH_PREFIX = "/api/v1/"
POST_METHOD = "POST"
DEVICE_ID_HEADER = "X-Device-Id"
TIMESTAMP_HEADER = "X-Timestamp"
NONCE_HEADER = "X-Nonce"
SIGNATURE_HEADER = "X-Signature"
CONTENT_TYPE_HEADER = "Content-Type"
NONCE_BYTES = 16
MAX_POINTS_PER_BATCH = 100
MAX_BODY_BYTES = 256 * 1024
SERVER_ERROR_FROM = 500
CLIENT_ERROR_FROM = 400
REJECTED_CODE_KEY = "error"


class TransportUnavailableError(Exception):
    """The request did not reach the API, or the API did not answer. The request can be retried."""


class TransportRejectedError(Exception):
    """The API answered with an error that a retry will not fix (for example, an invalid key)."""

    def __init__(self, status_code: int, code: str) -> None:
        message = f"La API rechazó la telemetría ({status_code}, {code})."
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class TelemetryRequest:
    """A POST to a device route: the path and the body bytes, which are never changed."""

    path: str
    body: bytes

    def __post_init__(self) -> None:
        if not self.path.startswith(API_PATH_PREFIX):
            raise ValueError("la ruta de telemetría debe empezar por /api/v1/")
        if len(self.body) > MAX_BODY_BYTES:
            raise ValueError("el cuerpo de telemetría supera 256 KiB")


def telemetry_request(points: Sequence[Mapping[str, Any]]) -> TelemetryRequest:
    """Builds one telemetry batch with the canonical JSON encoding of the simulator."""
    if not 1 <= len(points) <= MAX_POINTS_PER_BATCH:
        raise ValueError("un lote de telemetría tiene entre 1 y 100 puntos")
    return TelemetryRequest(TELEMETRY_PATH, encode_json({"points": list(points)}))


def canonical_string(method: str, path: str, timestamp: int, nonce: str, body: bytes) -> bytes:
    """The five-line string that the device signs, encoded in UTF-8."""
    body_sha256 = hashlib.sha256(body).hexdigest()
    return "\n".join([method, path, str(timestamp), nonce, body_sha256]).encode("utf-8")


def new_nonce() -> str:
    """128 random bits in lowercase hexadecimal (32 characters)."""
    return secrets.token_hex(NONCE_BYTES)


def unix_seconds() -> int:
    """Current instant as whole seconds since 1970-01-01T00:00:00Z."""
    return int(time.time())


class TelemetryTransport(Protocol):
    """Subject interface: sends one telemetry request, or raises a `TransportError`."""

    def send(self, request: TelemetryRequest) -> None:
        """Delivers the request. Raises `TransportUnavailableError` if it may be retried."""


@dataclass(frozen=True)
class DeviceIdentity:
    """Who signs the requests: the device identifier and its private Ed25519 key."""

    device_id: UUID
    private_key: Ed25519PrivateKey


class SignedHttpTransport:
    """Real subject: sends each request over HTTP, signed with the device key.

    The HTTP client is built by the caller (base URL and timeout). The clock and the nonce
    source are injected, so tests fix them. The transport never logs the key or the signature.

    This is the real subject of the offline proxy (P11).
    """

    def __init__(
        self,
        http: httpx.Client,
        identity: DeviceIdentity,
        *,
        clock: Callable[[], int] = unix_seconds,
        nonce_source: Callable[[], str] = new_nonce,
    ) -> None:
        self._http = http
        self._identity = identity
        self._clock = clock
        self._nonce_source = nonce_source

    def send(self, request: TelemetryRequest) -> None:
        timestamp = self._clock()
        nonce = self._nonce_source()
        signature = sign_bytes(
            canonical_string(POST_METHOD, request.path, timestamp, nonce, request.body),
            self._identity.private_key,
        )
        headers = {
            DEVICE_ID_HEADER: str(self._identity.device_id),
            TIMESTAMP_HEADER: str(timestamp),
            NONCE_HEADER: nonce,
            SIGNATURE_HEADER: signature,
            CONTENT_TYPE_HEADER: JSON_CONTENT_TYPE,
        }
        try:
            response = self._http.post(request.path, content=request.body, headers=headers)
        except httpx.TransportError as error:
            raise TransportUnavailableError("No se pudo conectar con la API.") from error
        if response.status_code >= SERVER_ERROR_FROM:
            raise TransportUnavailableError("La API no respondió correctamente.")
        if response.status_code >= CLIENT_ERROR_FROM:
            raise TransportRejectedError(response.status_code, _error_code(response))


def _error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
        return str(payload[REJECTED_CODE_KEY]["code"])
    except (ValueError, KeyError, TypeError):
        return "UNEXPECTED_RESPONSE"
