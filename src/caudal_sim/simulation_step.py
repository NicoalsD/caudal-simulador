"""One step of simulated time: the fixed sequence that every component follows.

A step always receives the orders that are due, advances the physical models by the same
elapsed time, and then reports the result. Concrete steps only decide what "advance" and
"report" mean for their own model: the valve node moves its valve, the tank applies the mass
balance of its water.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import final

from caudal_sim.tank import Tank, TankStep
from caudal_sim.valve_actuator import Actuator
from caudal_sim.valve_command_executor import ValveCommandExecutor

ONE_HOUR = timedelta(hours=1)
EMPTY_ELAPSED = timedelta(0)


class SimulationStep(ABC):
    """Template of one simulation step. `run` fixes the order; subclasses fill the hooks.

    The order is: receive the orders due at the start, advance the model, report the result at
    the end. `run` is final, so no subclass can change that order.

    @pattern P20 Template Method
    """

    @final
    def run(self, now: datetime, elapsed: timedelta) -> datetime:
        """Runs one step from `now` for `elapsed` and returns the instant it ends at."""
        if elapsed <= EMPTY_ELAPSED:
            raise ValueError("el paso de simulación debe avanzar tiempo")
        self._receive(now)
        self._advance(now, elapsed)
        end = now + elapsed
        self._report(end)
        return end

    def _receive(self, now: datetime) -> None:
        """Hook: takes the orders that are due at the start of the step. Does nothing by default."""
        return

    @abstractmethod
    def _advance(self, now: datetime, elapsed: timedelta) -> None:
        """Advances the model over the step."""

    def _report(self, end: datetime) -> None:
        """Hook: publishes the result at the end of the step. Does nothing by default."""
        return


class ValveNodeStep(SimulationStep):
    """Advances one valve node: it receives its orders, moves the valve, and confirms."""

    def __init__(self, executor: ValveCommandExecutor, actuator: Actuator) -> None:
        self._executor = executor
        self._actuator = actuator

    def _receive(self, now: datetime) -> None:
        self._executor.poll(now)

    def _advance(self, now: datetime, elapsed: timedelta) -> None:
        self._actuator.advance(elapsed)

    def _report(self, end: datetime) -> None:
        self._executor.poll(end)


class TankBalanceStep(SimulationStep):
    """Advances the tank by the mass balance of the step, using `Tank` for the volumes."""

    def __init__(
        self,
        tank: Tank,
        inflow_m3_per_hour: Callable[[datetime], float],
        outflow_m3_per_hour: Callable[[datetime], float],
    ) -> None:
        self._tank = tank
        self._inflow_m3_per_hour = inflow_m3_per_hour
        self._outflow_m3_per_hour = outflow_m3_per_hour
        self._last: TankStep | None = None

    @property
    def last_result(self) -> TankStep | None:
        """Result of the most recent step, or None before the first one."""
        return self._last

    def _advance(self, now: datetime, elapsed: timedelta) -> None:
        hours = elapsed / ONE_HOUR
        self._last = self._tank.step(
            self._inflow_m3_per_hour(now) * hours,
            self._outflow_m3_per_hour(now) * hours,
        )
