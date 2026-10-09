"""Simulated server side of valve commands: queue, delivery and confirmation.

The ledger keeps every command the board approved, hands the ones that are due to the valve
node, and records the confirmation. It follows the state table of `Protocolo-de-dispositivos.md`
(section 5.2): delivery is at least once, and an expired command is never delivered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from caudal_sim.event_bus import SimulationEvent, SimulationEventBus, SimulationEventKind
from caudal_sim.valve_commands import ValveCommand

MAX_COMMANDS_PER_DELIVERY = 100
MAX_ACK_DETAIL_LENGTH = 200


class CommandStatus(StrEnum):
    """Status of a command in the server, as in `devices.valve_commands.status`."""

    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    ACKED = "ACKED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AckResult(StrEnum):
    """Result that the valve node reports for a delivered command."""

    ACKED = "ACKED"
    FAILED = "FAILED"


class CommandNotFoundError(Exception):
    """The command does not exist in the ledger."""

    def __init__(self, command_id: UUID) -> None:
        message = f"No existe el comando {command_id}."
        super().__init__(message)
        self.command_id = command_id


class InvalidCommandTransitionError(Exception):
    """The requested change is not valid for the current status of the command."""

    def __init__(self, command_id: UUID, status: CommandStatus) -> None:
        message = f"El comando {command_id} en estado {status} no admite esta acción."
        super().__init__(message)
        self.command_id = command_id
        self.status = status


class CommandSource(Protocol):
    """What a valve node needs from the server: its commands and a way to confirm them."""

    def deliver(self, valve_id: UUID, now: datetime) -> tuple[ValveCommand, ...]:
        """Commands of the valve that are due at `now` and not yet confirmed."""

    def acknowledge(self, command_id: UUID, result: AckResult, detail: str, now: datetime) -> None:
        """Records the result that the valve node reports for a delivered command."""


@dataclass(frozen=True)
class LedgerEntryState:
    """Saved status of one command, with the detail of its confirmation."""

    command_id: UUID
    status: CommandStatus
    ack_detail: str


@dataclass
class _Entry:
    command: ValveCommand
    status: CommandStatus
    ack_detail: str = ""


class CommandLedger(CommandSource):
    """In-memory command table of the server, with the transitions of the protocol."""

    def __init__(self, bus: SimulationEventBus | None = None) -> None:
        self._entries: dict[UUID, _Entry] = {}
        self._bus = bus

    def enqueue(self, command: ValveCommand) -> None:
        """Adds a pending command. Its identifier must be new."""
        if command.command_id in self._entries:
            raise ValueError(f"El comando {command.command_id} ya está en la cola.")
        self._entries[command.command_id] = _Entry(command, CommandStatus.PENDING)

    def status_of(self, command_id: UUID) -> CommandStatus:
        return self._entry(command_id).status

    def command(self, command_id: UUID) -> ValveCommand:
        """The command with that identifier, as it was enqueued."""
        return self._entry(command_id).command

    def capture(self) -> tuple[LedgerEntryState, ...]:
        """Saved status of every command, ordered by identifier."""
        return tuple(
            LedgerEntryState(command_id, entry.status, entry.ack_detail)
            for command_id, entry in sorted(self._entries.items(), key=lambda item: str(item[0]))
        )

    def restore(self, states: tuple[LedgerEntryState, ...]) -> None:
        """Puts every command back in a saved status. The same commands must be enqueued."""
        if {state.command_id for state in states} != set(self._entries):
            raise ValueError("el estado guardado no corresponde a los mismos comandos")
        for state in states:
            entry = self._entries[state.command_id]
            entry.status = state.status
            entry.ack_detail = state.ack_detail

    def ack_detail_of(self, command_id: UUID) -> str:
        """Detail sent with the confirmation of a command, empty while it is not confirmed."""
        return self._entry(command_id).ack_detail

    def cancel(self, command_id: UUID) -> None:
        """Cancels a command that was not delivered yet (for example, the turn changed)."""
        entry = self._entry(command_id)
        if entry.status is not CommandStatus.PENDING:
            raise InvalidCommandTransitionError(command_id, entry.status)
        entry.status = CommandStatus.CANCELLED

    def expire_due(self, now: datetime) -> None:
        """Marks as EXPIRED every unconfirmed command whose `expires_at` has passed."""
        for entry in self._entries.values():
            is_open_order = entry.status in {CommandStatus.PENDING, CommandStatus.DELIVERED}
            if is_open_order and now >= entry.command.expires_at:
                entry.status = CommandStatus.EXPIRED

    def deliver(self, valve_id: UUID, now: datetime) -> tuple[ValveCommand, ...]:
        """Returns the due, unconfirmed commands of a valve, oldest first.

        A command moves from PENDING to DELIVERED the first time. A command already
        DELIVERED is sent again while it is still valid, because the node may not have seen it.
        """
        self.expire_due(now)
        due = sorted(
            (
                entry
                for entry in self._entries.values()
                if entry.command.valve_id == valve_id
                and entry.status in {CommandStatus.PENDING, CommandStatus.DELIVERED}
                and entry.command.not_before <= now
            ),
            key=lambda entry: entry.command.not_before,
        )[:MAX_COMMANDS_PER_DELIVERY]
        for entry in due:
            if entry.status is CommandStatus.PENDING:
                entry.status = CommandStatus.DELIVERED
                self._publish(
                    now, SimulationEventKind.COMMAND_DELIVERED, entry.command, entry.status
                )
        return tuple(entry.command for entry in due)

    def acknowledge(self, command_id: UUID, result: AckResult, detail: str, now: datetime) -> None:
        """Confirms a delivered command. Repeating the same confirmation changes nothing."""
        if len(detail) > MAX_ACK_DETAIL_LENGTH:
            raise ValueError(f"El detalle no puede superar {MAX_ACK_DETAIL_LENGTH} caracteres.")
        entry = self._entry(command_id)
        if entry.status is CommandStatus.DELIVERED:
            entry.status = CommandStatus(result)
            entry.ack_detail = detail
            self._publish(now, SimulationEventKind.COMMAND_CONFIRMED, entry.command, entry.status)
            return
        if entry.status.value == result.value:
            return
        raise InvalidCommandTransitionError(command_id, entry.status)

    def _entry(self, command_id: UUID) -> _Entry:
        try:
            return self._entries[command_id]
        except KeyError as error:
            raise CommandNotFoundError(command_id) from error

    def _publish(
        self,
        occurred_at: datetime,
        kind: SimulationEventKind,
        command: ValveCommand,
        status: CommandStatus,
    ) -> None:
        if self._bus is None:
            return
        self._bus.publish(
            SimulationEvent(
                occurred_at=occurred_at,
                kind=kind,
                subject_id=str(command.command_id),
                detail=f"{command.kind} {status}",
            )
        )
