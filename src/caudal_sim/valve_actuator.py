"""Simulated valve actuator: moves between the limit switches and reports its state.

The actuator follows the `ValveState` machine. A travel ends when the simulated time reaches
the travel time of the valve; then the matching limit switch is reached.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from caudal_sim.valve_state import ClosedState, ValveEvent, ValveState, ValveStatus

TRAVELLING_STATUSES = frozenset({ValveStatus.OPENING, ValveStatus.CLOSING})


class Actuator(Protocol):
    """Interface of a valve actuator as the rest of the simulator sees it."""

    @property
    def status(self) -> ValveStatus:
        """Position currently reported by the limit switches and the motor."""

    def request_open(self) -> None:
        """Starts opening the valve (or keeps it open)."""

    def request_close(self) -> None:
        """Starts closing the valve (or keeps it closed)."""

    def advance(self, elapsed: timedelta) -> None:
        """Moves the simulated time forward by `elapsed`."""


class ValveActuator:
    """Motorized ball valve with two limit switches and a fixed travel time.

    The valve starts closed. Reversing a travel restarts the travel time.
    """

    def __init__(self, travel_time: timedelta) -> None:
        if travel_time <= timedelta(0):
            raise ValueError("el tiempo de recorrido de la válvula debe ser mayor que cero")
        self._travel_time = travel_time
        self._state: ValveState = ClosedState()
        self._travelled = timedelta(0)

    @property
    def status(self) -> ValveStatus:
        return self._state.status

    def request_open(self) -> None:
        self._apply(ValveEvent.OPEN_REQUESTED)

    def request_close(self) -> None:
        self._apply(ValveEvent.CLOSE_REQUESTED)

    def advance(self, elapsed: timedelta) -> None:
        if elapsed < timedelta(0):
            raise ValueError("el tiempo transcurrido no puede ser negativo")
        if self.status not in TRAVELLING_STATUSES:
            return
        self._travelled += elapsed
        if self._travelled < self._travel_time:
            return
        if self.status is ValveStatus.OPENING:
            self._apply(ValveEvent.OPEN_LIMIT_REACHED)
        else:
            self._apply(ValveEvent.CLOSED_LIMIT_REACHED)

    def _apply(self, event: ValveEvent) -> None:
        previous = self.status
        self._state = self._state.handle(event)
        if self.status is not previous and self.status in TRAVELLING_STATUSES:
            self._travelled = timedelta(0)
