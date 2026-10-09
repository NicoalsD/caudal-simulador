"""Valve node side of the command exchange: applies due commands and reports the result.

The node asks the server for its commands, keeps only the newest one when several conflict
(`Protocolo-de-dispositivos.md`, section 5.5), moves the valve and confirms the command when
the valve reaches the requested position, or FAILED when the valve faults.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from caudal_sim.command_channel import AckResult, CommandSource
from caudal_sim.event_bus import SimulationEvent, SimulationEventBus, SimulationEventKind
from caudal_sim.valve_actuator import Actuator
from caudal_sim.valve_commands import ValveCommand, ValveCommandKind
from caudal_sim.valve_state import ValveStatus

SUPERSEDED_DETAIL = "Superado por un comando posterior para la misma válvula."
FAULT_DETAIL = "Falla de válvula: el final de carrera no llegó en el tiempo máximo."
REACHED_DETAIL = "Válvula en la posición pedida; posición confirmada."
TARGET_STATUS: dict[ValveCommandKind, ValveStatus] = {
    ValveCommandKind.OPEN: ValveStatus.OPEN,
    ValveCommandKind.CLOSE: ValveStatus.CLOSED,
}


@dataclass(frozen=True)
class ExecutorState:
    """Saved progress of a node: the command in flight and the last status it published."""

    in_flight: ValveCommand | None
    last_status: ValveStatus


class ValveCommandExecutor:
    """Node that polls its commands from a `CommandSource` and drives its own actuator."""

    def __init__(
        self,
        valve_id: UUID,
        actuator: Actuator,
        source: CommandSource,
        bus: SimulationEventBus,
    ) -> None:
        self._valve_id = valve_id
        self._actuator = actuator
        self._source = source
        self._bus = bus
        self._in_flight: ValveCommand | None = None
        self._last_status = actuator.status

    def poll(self, now: datetime) -> None:
        """One exchange: receive, resolve conflicts, execute, then confirm if the valve is done."""
        delivered = self._source.deliver(self._valve_id, now)
        winner = _newest(delivered)
        for command in delivered:
            if command is not winner:
                self._source.acknowledge(
                    command.command_id, AckResult.FAILED, SUPERSEDED_DETAIL, now
                )
        if winner is not None and winner is not self._in_flight:
            winner.execute(now, self._actuator)
            self._in_flight = winner
        self._publish_status_change(now)
        self._confirm_in_flight(now)

    def capture(self) -> ExecutorState:
        """Saved progress of the node, independent of later polls."""
        return ExecutorState(in_flight=self._in_flight, last_status=self._last_status)

    def restore(self, state: ExecutorState) -> None:
        """Puts the node back at a saved progress. Commands are immutable, so they are shared."""
        self._in_flight = state.in_flight
        self._last_status = state.last_status

    def _confirm_in_flight(self, now: datetime) -> None:
        command = self._in_flight
        if command is None:
            return
        status = self._actuator.status
        if status is ValveStatus.FAULT:
            self._source.acknowledge(command.command_id, AckResult.FAILED, FAULT_DETAIL, now)
            self._in_flight = None
        elif status is TARGET_STATUS[command.kind]:
            self._source.acknowledge(command.command_id, AckResult.ACKED, REACHED_DETAIL, now)
            self._in_flight = None

    def _publish_status_change(self, now: datetime) -> None:
        status = self._actuator.status
        if status is self._last_status:
            return
        self._last_status = status
        self._bus.publish(
            SimulationEvent(
                occurred_at=now,
                kind=SimulationEventKind.VALVE_STATE_CHANGED,
                subject_id=str(self._valve_id),
                detail=str(status),
            )
        )


def _newest(commands: tuple[ValveCommand, ...]) -> ValveCommand | None:
    """The command with the latest `not_before`. On a tie, the one delivered last wins."""
    winner: ValveCommand | None = None
    for command in commands:
        if winner is None or command.not_before >= winner.not_before:
            winner = command
    return winner
