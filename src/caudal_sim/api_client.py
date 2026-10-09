"""HTTP client for the CAUDAL API: login, public schedule and the import endpoints.

The client authenticates as the simulated PROJECT_TEAM user and keeps the access token in
memory only. It never logs the password or the token. Canonical error bodies are turned
into `ApiError`, which carries the contract code and the Spanish message.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import SecretStr

LOGIN_PATH = "/api/v1/auth/login"
PUBLIC_SCHEDULE_PATH = "/api/v1/public/{slug}/schedule"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "
JSON_CONTENT_TYPE = "application/json"
CONTENT_TYPE_HEADER = "Content-Type"
ERROR_KEY = "error"
UNEXPECTED_ERROR_CODE = "UNEXPECTED_RESPONSE"
UNEXPECTED_ERROR_MESSAGE = "La API devolvió una respuesta inesperada."
UNKNOWN_STATUS = 0
JSON_SEPARATORS = (",", ":")


class ApiError(Exception):
    """A non-success answer from the API, with its canonical code and Spanish message."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class CaudalApiClient:
    """Synchronous client for the endpoints the simulator uses.

    Pass `transport` to replace the network, for example an `httpx.MockTransport` in tests.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            transport=transport,
            headers={"Accept": JSON_CONTENT_TYPE},
        )
        self._token: str | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Closes the HTTP connection pool and forgets the access token."""
        self._token = None
        self._http.close()

    def login(self, username: str, password: SecretStr) -> None:
        """Authenticates and keeps the access token in memory for later calls."""
        body = self._request(
            "POST",
            LOGIN_PATH,
            body={"username": username, "password": password.get_secret_value()},
        )
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise ApiError(UNKNOWN_STATUS, UNEXPECTED_ERROR_CODE, UNEXPECTED_ERROR_MESSAGE)
        self._token = token

    def get_public_schedule(self, slug: str) -> Mapping[str, Any]:
        """Public schedule of an aqueduct. Its `aqueduct` block states `is_demo`."""
        return self._request("GET", PUBLIC_SCHEDULE_PATH.format(slug=slug))

    def post_import(self, path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        """Sends one import batch. Requires a prior successful `login`."""
        if self._token is None:
            raise ApiError(UNKNOWN_STATUS, "UNAUTHORIZED", "Primero inicia sesión en la API.")
        return self._request(
            "POST",
            path,
            body=body,
            headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX}{self._token}"},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        request_headers = dict(headers or {})
        content: bytes | None = None
        if body is not None:
            content = encode_json(body)
            request_headers[CONTENT_TYPE_HEADER] = JSON_CONTENT_TYPE
        try:
            response = self._http.request(method, path, content=content, headers=request_headers)
        except httpx.HTTPError as error:
            raise ApiError(
                UNKNOWN_STATUS,
                "CONNECTION_FAILED",
                "No se pudo conectar con la API. Revisa la URL y la red.",
            ) from error
        if response.is_success:
            return _json_object(response)
        raise _error_from(response)


def encode_json(body: Mapping[str, Any]) -> bytes:
    """Canonical UTF-8 JSON: sorted keys, no extra spaces, so that its size is predictable."""
    return json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=JSON_SEPARATORS, allow_nan=False
    ).encode("utf-8")


def _json_object(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise ApiError(
            response.status_code, UNEXPECTED_ERROR_CODE, UNEXPECTED_ERROR_MESSAGE
        ) from error
    if not isinstance(payload, dict):
        raise ApiError(response.status_code, UNEXPECTED_ERROR_CODE, UNEXPECTED_ERROR_MESSAGE)
    return payload


def _error_from(response: httpx.Response) -> ApiError:
    try:
        payload = response.json()
        error = payload[ERROR_KEY]
        code = str(error["code"])
        message = str(error["message"])
    except (ValueError, KeyError, TypeError):
        return ApiError(response.status_code, UNEXPECTED_ERROR_CODE, UNEXPECTED_ERROR_MESSAGE)
    return ApiError(response.status_code, code, message)
