"""Simulated valve actuator: moves between the limit switches and reports its state.

The actuator follows the `ValveState` machine and delegates the motor to an `ActuatorDriver`.
A travel that ends at the limit switch goes to OPEN or CLOSED. A travel that exceeds the
maximum travel time stops the motor and goes to FAULT.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from caudal_sim.actuator_driver import ActuatorDriver, MotorDirection
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
    """Motorized ball valve: the valve logic (abstraction) over a motor driver (implementor).

    The valve starts closed. Reversing a travel restarts the travel time.

    @pattern P07 Bridge
    """

    def __init__(self, driver: ActuatorDriver, max_travel_time: timedelta) -> None:
        if max_travel_time <= timedelta(0):
            raise ValueError("el tiempo máximo de maniobra debe ser mayor que cero")
        if max_travel_time < driver.travel_time:
            raise ValueError("el tiempo máximo de maniobra no puede ser menor que el recorrido")
        self._driver = driver
        self._max_travel_time = max_travel_time
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
        if self._driver.limit_reached_after(self._travelled):
            if self.status is ValveStatus.OPENING:
                self._apply(ValveEvent.OPEN_LIMIT_REACHED)
            else:
                self._apply(ValveEvent.CLOSED_LIMIT_REACHED)
        elif self._travelled >= self._max_travel_time:
            self._apply(ValveEvent.TRAVEL_TIMEOUT)

    def _apply(self, event: ValveEvent) -> None:
        previous = self.status
        self._state = self._state.handle(event)
        if self.status is previous:
            return
        if previous in TRAVELLING_STATUSES:
            self._driver.stop()
        if self.status in TRAVELLING_STATUSES:
            self._travelled = timedelta(0)
            direction = (
                MotorDirection.OPEN if self.status is ValveStatus.OPENING else MotorDirection.CLOSE
            )
            self._driver.start(direction)
