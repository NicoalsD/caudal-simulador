"""HTTP side of the valve commands of one maqueta outlet: the signed GET and the signed ack.

The API hands a device its commands in `GET /api/v1/devices/commands` and takes the result in
`POST /api/v1/devices/commands/{id}/ack`. This module turns the JSON of the API into the
`ValveCommand` objects of the simulator, so `ValveCommandExecutor` runs them the same way it
runs the in-process commands. The executor keeps the protocol rules (`Protocolo-de-dispositivos.md`,
sections 5.3 to 5.5); this module only translates and reports.

A command this maqueta does not understand (an unknown action, or another valve) is acknowledged
as FAILED, so the server stops sending it. A command outside its window is left alone: the server
expires it by itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from caudal_sim.api_client import encode_json
from caudal_sim.command_channel import AckResult, CommandSource
from caudal_sim.telemetry_transport import (
    SignedHttpTransport,
    TransportRejectedError,
    TransportUnavailableError,
)
from caudal_sim.valve_commands import CloseValveCommand, OpenValveCommand, ValveCommand

COMMANDS_PATH = "/api/v1/devices/commands"
ACK_PATH_TEMPLATE = "/api/v1/devices/commands/{command_id}/ack"
GET_METHOD = "GET"
POST_METHOD = "POST"
ITEMS_KEY = "items"
MAX_ACK_DETAIL_LENGTH = 200
UNKNOWN_COMMAND_DETAIL = "Comando desconocido para la maqueta: la acción o la válvula no existen."
BAD_WINDOW_DETAIL = "Ventana de comando inválida para la maqueta."
KINDS: dict[str, type[ValveCommand]] = {"OPEN": OpenValveCommand, "CLOSE": CloseValveCommand}


class UnknownCommandError(ValueError):
    """A command the maqueta cannot run. `command_id` is None when even the id is unreadable."""

    def __init__(self, command_id: UUID | None, detail: str) -> None:
        super().__init__(detail)
        self.command_id = command_id
        self.detail = detail


class HttpCommandSource(CommandSource):
    """Command source of one valve: pulls the device's commands and confirms them by HTTP.

    The transport is the signed one of the actuator device. Network failures never escape from
    `acknowledge`: they are counted, and the server sends the command again, because the executor
    acknowledges an already-applied command again without moving the valve.

    @pattern P06 Adapter (the JSON of the API becomes `ValveCommand`)
    """

    def __init__(
        self,
        transport: SignedHttpTransport,
        valve_id: UUID,
        parse_instant: Callable[[str], datetime],
    ) -> None:
        self._transport = transport
        self._valve_id = valve_id
        self._parse_instant = parse_instant
        self._network_errors = 0
        self._last_error = ""

    @property
    def network_errors(self) -> int:
        """Failed exchanges with the API so far (the run goes on after each one)."""
        return self._network_errors

    @property
    def last_error(self) -> str:
        """Message of the last failed exchange, empty when there was none."""
        return self._last_error

    def deliver(self, valve_id: UUID, now: datetime) -> tuple[ValveCommand, ...]:
        """Commands of the valve that are due at `now`. Raises on a failed GET, for the caller."""
        if valve_id != self._valve_id:
            return ()
        response = self._transport.exchange(GET_METHOD, COMMANDS_PATH)
        items = _items_of(response.json())
        due: list[ValveCommand] = []
        for item in items:
            try:
                command = self._to_command(item)
            except UnknownCommandError as error:
                if error.command_id is not None:
                    self.acknowledge(error.command_id, AckResult.FAILED, error.detail, now)
                continue
            if not command.is_executable_at(now):
                continue
            due.append(command)
        return tuple(due)

    def acknowledge(self, command_id: UUID, result: AckResult, detail: str, now: datetime) -> None:
        """Sends the result of a command. A failure is counted, not raised."""
        del now  # the server sets the confirmation instant itself
        body = encode_json({"result": result.value, "detail": detail[:MAX_ACK_DETAIL_LENGTH]})
        path = ACK_PATH_TEMPLATE.format(command_id=command_id)
        try:
            self._transport.exchange(POST_METHOD, path, body)
        except (TransportUnavailableError, TransportRejectedError) as error:
            self._network_errors += 1
            self._last_error = str(error)

    def _to_command(self, item: Mapping[str, Any]) -> ValveCommand:
        try:
            command_id = UUID(str(item.get("id")))
        except ValueError as error:
            raise UnknownCommandError(None, UNKNOWN_COMMAND_DETAIL) from error
        command_class = KINDS.get(str(item.get("command")))
        if command_class is None:
            raise UnknownCommandError(command_id, UNKNOWN_COMMAND_DETAIL)
        try:
            valve_id = UUID(str(item.get("valve_id")))
        except ValueError as error:
            raise UnknownCommandError(command_id, UNKNOWN_COMMAND_DETAIL) from error
        if valve_id != self._valve_id:
            raise UnknownCommandError(command_id, UNKNOWN_COMMAND_DETAIL)
        try:
            not_before = self._parse_instant(str(item.get("not_before")))
            expires_at = self._parse_instant(str(item.get("expires_at")))
            return command_class(command_id, valve_id, not_before, expires_at)
        except ValueError as error:
            raise UnknownCommandError(command_id, BAD_WINDOW_DETAIL) from error


def _items_of(payload: object) -> list[Mapping[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get(ITEMS_KEY), list):
        return []
    return [item for item in payload[ITEMS_KEY] if isinstance(item, dict)]
