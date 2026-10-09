"""State of a simulated motorized valve: the five positions the field node can report.

The valve moves between OPEN and CLOSED through the intermediate states OPENING and CLOSING.
A travel that does not end before its time limit goes to FAULT, and a FAULT valve only moves
again when a new order arrives: the node never retries by itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class ValveStatus(StrEnum):
    """Position reported by the limit switches, plus the two travels and the fault."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    OPENING = "OPENING"
    CLOSING = "CLOSING"
    FAULT = "FAULT"


class ValveEvent(StrEnum):
    """Inputs that move the valve: an order, a limit switch reached or a travel timeout."""

    OPEN_REQUESTED = "OPEN_REQUESTED"
    CLOSE_REQUESTED = "CLOSE_REQUESTED"
    OPEN_LIMIT_REACHED = "OPEN_LIMIT_REACHED"
    CLOSED_LIMIT_REACHED = "CLOSED_LIMIT_REACHED"
    TRAVEL_TIMEOUT = "TRAVEL_TIMEOUT"


class InvalidValveTransitionError(Exception):
    """An event that the current valve state does not accept."""

    def __init__(self, status: ValveStatus, event: ValveEvent) -> None:
        message = f"La válvula en estado {status} no acepta el evento {event}."
        super().__init__(message)
        self.status = status
        self.event = event


class ValveState(ABC):
    """State interface of the valve. Each concrete state decides its own transitions.

    Repeating an order that the valve already follows (opening while opening, closing while
    closed) is accepted and changes nothing, because the protocol delivers commands at least
    once.

    @pattern P18 State
    """

    @property
    @abstractmethod
    def status(self) -> ValveStatus:
        """The position this state reports."""

    @abstractmethod
    def handle(self, event: ValveEvent) -> ValveState:
        """Returns the state after `event`, or raises `InvalidValveTransitionError`."""

    def _invalid(self, event: ValveEvent) -> InvalidValveTransitionError:
        return InvalidValveTransitionError(self.status, event)


class ClosedState(ValveState):
    """Closed: the only state from which an opening starts."""

    @property
    def status(self) -> ValveStatus:
        return ValveStatus.CLOSED

    def handle(self, event: ValveEvent) -> ValveState:
        if event is ValveEvent.OPEN_REQUESTED:
            return OpeningState()
        if event is ValveEvent.CLOSE_REQUESTED:
            return self
        raise self._invalid(event)


class OpeningState(ValveState):
    """Opening: the motor runs towards the open limit switch."""

    @property
    def status(self) -> ValveStatus:
        return ValveStatus.OPENING

    def handle(self, event: ValveEvent) -> ValveState:
        if event is ValveEvent.OPEN_REQUESTED:
            return self
        if event is ValveEvent.OPEN_LIMIT_REACHED:
            return OpenState()
        if event is ValveEvent.CLOSE_REQUESTED:
            return ClosingState()
        if event is ValveEvent.TRAVEL_TIMEOUT:
            return FaultState()
        raise self._invalid(event)


class OpenState(ValveState):
    """Open: the sector receives water."""

    @property
    def status(self) -> ValveStatus:
        return ValveStatus.OPEN

    def handle(self, event: ValveEvent) -> ValveState:
        if event is ValveEvent.OPEN_REQUESTED:
            return self
        if event is ValveEvent.CLOSE_REQUESTED:
            return ClosingState()
        raise self._invalid(event)


class ClosingState(ValveState):
    """Closing: the motor runs towards the closed limit switch."""

    @property
    def status(self) -> ValveStatus:
        return ValveStatus.CLOSING

    def handle(self, event: ValveEvent) -> ValveState:
        if event is ValveEvent.CLOSE_REQUESTED:
            return self
        if event is ValveEvent.CLOSED_LIMIT_REACHED:
            return ClosedState()
        if event is ValveEvent.OPEN_REQUESTED:
            return OpeningState()
        if event is ValveEvent.TRAVEL_TIMEOUT:
            return FaultState()
        raise self._invalid(event)


class FaultState(ValveState):
    """Fault: the motor stopped before a limit switch. Only a new order leaves this state."""

    @property
    def status(self) -> ValveStatus:
        return ValveStatus.FAULT

    def handle(self, event: ValveEvent) -> ValveState:
        if event is ValveEvent.OPEN_REQUESTED:
            return OpeningState()
        if event is ValveEvent.CLOSE_REQUESTED:
            return ClosingState()
        raise self._invalid(event)


_STATES_BY_STATUS: dict[ValveStatus, type[ValveState]] = {
    ValveStatus.CLOSED: ClosedState,
    ValveStatus.OPENING: OpeningState,
    ValveStatus.OPEN: OpenState,
    ValveStatus.CLOSING: ClosingState,
    ValveStatus.FAULT: FaultState,
}


def state_for(status: ValveStatus) -> ValveState:
    """Concrete state object for a status, for example to restore a valve from a snapshot."""
    return _STATES_BY_STATUS[status]()
