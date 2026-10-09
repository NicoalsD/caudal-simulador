"""Valve commands: an order to open or close a valve, valid only inside its time window.

A command carries `not_before` and `expires_at`. The valve never runs it before the first
instant nor at or after the second one, so a late command is discarded instead of opening
water outside the approved shift.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from caudal_sim.valve_actuator import Actuator


class ValveCommandKind(StrEnum):
    """Order of a command, as the API names it."""

    OPEN = "OPEN"
    CLOSE = "CLOSE"


class ValveCommand(ABC):
    """Command interface: `execute` checks the window, `apply` moves the valve.

    @pattern P13 Command
    """

    kind: ValveCommandKind

    def __init__(
        self,
        command_id: UUID,
        valve_id: UUID,
        not_before: datetime,
        expires_at: datetime,
    ) -> None:
        if not_before.utcoffset() is None or expires_at.utcoffset() is None:
            raise ValueError("los instantes del comando deben tener zona horaria")
        if expires_at <= not_before:
            raise ValueError("el comando debe vencer después de su hora de inicio")
        self._command_id = command_id
        self._valve_id = valve_id
        self._not_before = not_before
        self._expires_at = expires_at

    @property
    def command_id(self) -> UUID:
        return self._command_id

    @property
    def valve_id(self) -> UUID:
        return self._valve_id

    @property
    def not_before(self) -> datetime:
        return self._not_before

    @property
    def expires_at(self) -> datetime:
        return self._expires_at

    def __eq__(self, other: object) -> bool:
        """Two commands are equal when they carry the same order, valve and window."""
        if not isinstance(other, ValveCommand):
            return NotImplemented
        return (
            type(self) is type(other)
            and self._command_id == other._command_id
            and self._valve_id == other._valve_id
            and self._not_before == other._not_before
            and self._expires_at == other._expires_at
        )

    def __hash__(self) -> int:
        return hash((self.kind, self._command_id))

    def is_executable_at(self, now: datetime) -> bool:
        """True inside `[not_before, expires_at)`."""
        return self._not_before <= now < self._expires_at

    def execute(self, now: datetime, actuator: Actuator) -> bool:
        """Applies the command if `now` is inside its window. Returns whether it was applied."""
        if not self.is_executable_at(now):
            return False
        self.apply(actuator)
        return True

    @abstractmethod
    def apply(self, actuator: Actuator) -> None:
        """Gives the order to the actuator (the receiver)."""


class OpenValveCommand(ValveCommand):
    """Order to open the valve."""

    kind = ValveCommandKind.OPEN

    def apply(self, actuator: Actuator) -> None:
        actuator.request_open()


class CloseValveCommand(ValveCommand):
    """Order to close the valve."""

    kind = ValveCommandKind.CLOSE

    def apply(self, actuator: Actuator) -> None:
        actuator.request_close()
