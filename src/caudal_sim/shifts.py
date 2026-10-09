"""Turnos: cumplimiento del horario publicado (cumplido, a medias o no cumplido)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.scenario import ScheduleSpec


class ShiftOutcome(StrEnum):
    """Resultado de un turno, tal como lo registra el fontanero al final del día."""

    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    NOT_EXECUTED = "NOT_EXECUTED"


@dataclass(frozen=True)
class ShiftExecution:
    """Un turno de un día: su ventana publicada, su resultado y las horas abiertas."""

    day_index: int
    sector_id: str
    start_hour: int
    end_hour: int
    outcome: ShiftOutcome
    open_hours: int


@dataclass(frozen=True)
class ShiftRun:
    """Válvulas abiertas por hora (una serie por sector) y el registro de los turnos."""

    valve_open: dict[str, npt.NDArray[np.bool_]]
    executions: tuple[ShiftExecution, ...]


class ShiftSimulator:
    """Sigue el horario publicado y decide, por turno, si se cumplió.

    Cumplido abre la válvula en toda la ventana. A medias la cierra a la mitad de la
    ventana. No cumplido no la abre. Un sector puede tener varios turnos en el día.

    Sin @pattern: el horario es un dato del escenario, no un algoritmo intercambiable.
    """

    def __init__(self, schedule: ScheduleSpec, sector_ids: Sequence[str]) -> None:
        self._schedule = schedule
        self._sector_ids = list(sector_ids)
        unknown = {turn.sector for turn in schedule.turns} - set(self._sector_ids)
        if unknown:
            raise ValueError(f"el horario usa sectores desconocidos: {sorted(unknown)}")

    def simulate(self, days: int, rng: np.random.Generator) -> ShiftRun:
        turns = self._schedule.turns
        draws = rng.random(days * len(turns))
        hours = days * HOURS_PER_DAY
        valve_open = {sector_id: np.zeros(hours, dtype=np.bool_) for sector_id in self._sector_ids}
        executions: list[ShiftExecution] = []

        for index, (day, turn_index) in enumerate(
            (day, turn_index) for day in range(days) for turn_index in range(len(turns))
        ):
            turn = turns[turn_index]
            outcome = self._outcome(draws[index])
            open_hours = self._open_hours(turn.start_hour, turn.end_hour, outcome)
            first = day * HOURS_PER_DAY + turn.start_hour
            valve_open[turn.sector][first : first + open_hours] = True
            executions.append(
                ShiftExecution(
                    day_index=day,
                    sector_id=turn.sector,
                    start_hour=turn.start_hour,
                    end_hour=turn.end_hour,
                    outcome=outcome,
                    open_hours=open_hours,
                )
            )
        return ShiftRun(valve_open=valve_open, executions=tuple(executions))

    def _outcome(self, draw: float) -> ShiftOutcome:
        if draw < self._schedule.p_completed:
            return ShiftOutcome.COMPLETED
        if draw < self._schedule.p_completed + self._schedule.p_partial:
            return ShiftOutcome.PARTIAL
        return ShiftOutcome.NOT_EXECUTED

    @staticmethod
    def _open_hours(start_hour: int, end_hour: int, outcome: ShiftOutcome) -> int:
        window = end_hour - start_hour
        if outcome is ShiftOutcome.COMPLETED:
            return window
        if outcome is ShiftOutcome.PARTIAL:
            return window // 2
        return 0
